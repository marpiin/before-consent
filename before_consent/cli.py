"""Command line interface: doctor, fetch-lists, verify-targets, run, report, export."""

import argparse
import csv
import re
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from before_consent import __version__, store
from before_consent.audit import run_audit, verify_targets
from before_consent.config import (
    BROWSER_CHANNELS,
    ConfigError,
    Settings,
    load_settings,
    require_contact,
    settings_sha256,
)
from before_consent.lists import LIST_FILE, fetch_disconnect, read_snapshot
from before_consent.netguard import GuardProxy
from before_consent.pacing import Pacer
from before_consent.report import build_report, export_csv, latest_run
from before_consent.targets import load_targets
from before_consent.trackers import load_disconnect
from before_consent.visit import BrowserSession, honest_user_agent, launch_browser

DEFAULT_CONFIG = Path("before-consent.toml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="before-consent", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="settings file")
    parser.add_argument(
        "--browser-channel",
        choices=BROWSER_CHANNELS,
        help="override the settings file; use chrome or msedge if the bundled Chromium is "
        "blocked on this machine",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor", help="check browser, database, lists and settings")
    commands.add_parser("fetch-lists", help="download the Disconnect tracker list")

    verify = commands.add_parser(
        "verify-targets", help="check DNS, robots.txt and HTTP status once per target"
    )
    verify.add_argument("--limit", type=int, help="only the first N targets")
    verify.add_argument("--allow-local", action="store_true", help=argparse.SUPPRESS)

    run = commands.add_parser("run", help="visit the targets and store what loaded")
    run.add_argument("--country", required=True, help="ISO code of where you measure from")
    run.add_argument("--limit", type=int, help="only the first N targets")
    run.add_argument("--repetitions", type=int, help="override the settings file")
    run.add_argument("--note", help="free text stored with the run")
    # Only for tests against servers on this machine; never needed for public sites.
    run.add_argument("--allow-local", action="store_true", help=argparse.SUPPRESS)

    for name, text in (("report", "write the HTML report"), ("export", "write aggregated CSVs")):
        command = commands.add_parser(name, help=text)
        command.add_argument("--run-id", type=int, help="default: the latest finished run")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
        if args.browser_channel:
            settings = replace(settings, browser_channel=args.browser_channel)
        command = COMMANDS[args.command]
        return command(args, settings)
    except (ConfigError, ValueError, OSError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


@contextmanager
def browser_session(
    settings: Settings, contact: str, allow_local: bool = False
) -> Iterator[BrowserSession]:
    snapshot_dir = Path(settings.lists_dir)
    if read_snapshot(snapshot_dir) is None:
        raise ConfigError("tracker list missing; run the fetch-lists command first")
    trackers = load_disconnect(snapshot_dir / LIST_FILE)
    proxy = GuardProxy(allow_local=allow_local).start()
    try:
        with sync_playwright() as playwright:
            browser = launch_browser(playwright, settings.browser_channel, proxy)
            try:
                yield BrowserSession(
                    browser=browser,
                    proxy=proxy,
                    settings=settings,
                    trackers=trackers,
                    user_agent=honest_user_agent(browser, contact),
                )
            finally:
                browser.close()
    finally:
        proxy.stop()


def cmd_fetch_lists(args: argparse.Namespace, settings: Settings) -> int:
    snapshot = fetch_disconnect(Path(settings.lists_dir))
    print(f"saved {snapshot.size_bytes} bytes from {snapshot.source_url}")
    print(f"sha256 {snapshot.sha256}, fetched {snapshot.fetched_at}, license {snapshot.license}")
    return 0


def cmd_verify_targets(args: argparse.Namespace, settings: Settings) -> int:
    contact = require_contact(settings)
    targets = load_targets(Path(settings.targets))[: args.limit]
    pacer = Pacer(settings.gap_seconds, settings.same_site_gap_seconds)
    with browser_session(settings, contact, args.allow_local) as session:
        checks = verify_targets(session, targets, pacer)
    out = Path(settings.database).parent / "targets-verification.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(checks[0])) if checks else ["url"])
        writer.writeheader()
        writer.writerows(asdict(check) for check in checks)
    print(f"wrote {out}; review it and update targets.csv by hand")
    return 0


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    contact = require_contact(settings)
    if not re.fullmatch(r"[A-Z]{2}", args.country):
        raise ConfigError("--country must be a two-letter ISO code such as ES")
    if args.repetitions:
        settings = replace(settings, repetitions=args.repetitions)
    targets = load_targets(Path(settings.targets))[: args.limit]
    snapshot = read_snapshot(Path(settings.lists_dir))
    connection = store.connect(settings.database)
    pacer = Pacer(settings.gap_seconds, settings.same_site_gap_seconds)
    with browser_session(settings, contact, args.allow_local) as session:
        run_id = store.start_run(
            connection,
            country=args.country,
            browser_channel=settings.browser_channel,
            browser_version=session.browser.version,
            snapshot=snapshot,
            config_sha256=settings_sha256(settings),
            note=args.note,
        )
        print(f"run {run_id}: {len(targets)} targets x {settings.repetitions} rounds")
        run_audit(session, connection, run_id, targets, pacer)
    store.finish_run(connection, run_id)
    print(f"run {run_id} finished; database {settings.database}")
    return 0


def cmd_export(args: argparse.Namespace, settings: Settings) -> int:
    connection = store.connect(settings.database)
    run_id = args.run_id or latest_run(connection)
    out_dir = Path(settings.report_dir) / "data"
    for path in export_csv(connection, run_id, settings, out_dir):
        print(f"wrote {path}")
    return 0


def cmd_report(args: argparse.Namespace, settings: Settings) -> int:
    connection = store.connect(settings.database)
    run_id = args.run_id or latest_run(connection)
    path = build_report(connection, run_id, settings, Path(settings.report_dir))
    print(f"wrote {path}")
    return 0


def cmd_doctor(args: argparse.Namespace, settings: Settings) -> int:
    problems = 0

    def report(ok: bool, what: str, fix: str = "") -> None:
        nonlocal problems
        problems += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {what}" + (f"\n     {fix}" if fix and not ok else ""))

    report(sys.version_info >= (3, 11), f"Python {sys.version.split()[0]}", "Use Python 3.11+.")

    proxy = GuardProxy().start()
    try:
        with sync_playwright() as playwright:
            browser = launch_browser(playwright, settings.browser_channel, proxy)
            version = browser.version
            browser.close()
        report(True, f"browser {settings.browser_channel} {version} starts with its sandbox on")
    except PlaywrightError as error:
        first = str(error).strip().splitlines()[0] if str(error).strip() else "unknown error"
        report(
            False,
            f"browser {settings.browser_channel} does not start: {first}",
            "Run `python -m playwright install chromium`. If Windows application control blocks"
            " it, try --browser-channel msedge or --browser-channel chrome.",
        )
    finally:
        proxy.stop()

    try:
        connection = store.connect(settings.database)
        connection.execute("CREATE TEMP TABLE doctor_probe (x)")
        connection.execute("INSERT INTO doctor_probe VALUES (1)")
        connection.close()
        report(True, f"database {settings.database} is writable")
    except (sqlite3.Error, OSError) as error:
        report(False, f"database {settings.database}: {error}", "Check the path and permissions.")

    snapshot = read_snapshot(Path(settings.lists_dir))
    report(
        snapshot is not None,
        f"tracker list fetched {snapshot.fetched_at}, sha256 {snapshot.sha256[:12]}"
        if snapshot
        else "tracker list is missing",
        "Run `python -m before_consent fetch-lists`.",
    )

    try:
        targets = load_targets(Path(settings.targets))
        report(True, f"{len(targets)} targets in {settings.targets}")
    except (OSError, ValueError) as error:
        report(False, f"targets: {error}", "Fix targets.csv (columns url, category).")

    try:
        require_contact(settings)
        report(True, "contact is set")
    except ConfigError as error:
        report(False, str(error), f"Edit {args.config}.")

    print("all checks passed" if not problems else f"{problems} check(s) failed")
    return 0 if not problems else 1


COMMANDS = {
    "doctor": cmd_doctor,
    "fetch-lists": cmd_fetch_lists,
    "verify-targets": cmd_verify_targets,
    "run": cmd_run,
    "report": cmd_report,
    "export": cmd_export,
}
