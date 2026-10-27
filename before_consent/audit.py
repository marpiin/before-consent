"""The run loop: robots first, then one polite visit at a time in rotating order."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from before_consent import store
from before_consent.netguard import host_verdict
from before_consent.pacing import Pacer, rotation
from before_consent.records import VisitResult
from before_consent.robots import RobotsDecision
from before_consent.targets import Target
from before_consent.visit import BrowserSession, check_robots, fetch_document, visit_site

Progress = Callable[[str], None]


def run_audit(
    session: BrowserSession,
    connection: sqlite3.Connection,
    run_id: int,
    targets: list[Target],
    pacer: Pacer,
    progress: Progress = print,
) -> None:
    robots: dict[str, RobotsDecision] = {}
    plan = rotation(targets, session.settings.repetitions)
    for number, (target, round_) in enumerate(plan, start=1):
        site = store.site_id(connection, target.url, target.category)
        decision = robots.get(target.url)
        if decision is not None and not decision.allowed:
            result = VisitResult(url=target.url, status="skipped_robots", error=decision.reason)
        else:
            pacer.wait_turn(target.url)
            try:
                if decision is None:
                    decision = robots[target.url] = check_robots(session, target.url)
                if decision.allowed:
                    result = visit_site(session, target.url)
                else:
                    result = VisitResult(
                        url=target.url, status="skipped_robots", error=decision.reason
                    )
            # One broken site must not end a run that takes hours. The cause is stored with
            # the visit and shows up in the report.
            except Exception as error:  # noqa: BLE001
                result = VisitResult(
                    url=target.url, status="failed", error=f"{type(error).__name__}: {error}"
                )
            finally:
                pacer.finished(target.url)
        store.save_visit(connection, run_id, site, round_, result)
        detail = f" ({result.error})" if result.error else ""
        progress(f"[{number}/{len(plan)}] round {round_} {target.url}: {result.status}{detail}")


@dataclass(frozen=True)
class TargetCheck:
    url: str
    category: str
    dns: str
    robots: str
    http_status: int | None
    final_host: str | None
    problem: str | None


def verify_targets(
    session: BrowserSession, targets: list[Target], pacer: Pacer, progress: Progress = print
) -> list[TargetCheck]:
    checks = []
    for target in targets:
        host = urlsplit(target.url).hostname or ""
        dns = host_verdict(host, session.proxy.resolve, session.proxy.allow_local)
        if not dns.allowed:
            check = TargetCheck(target.url, target.category, dns.reason, "", None, None, dns.reason)
        else:
            pacer.wait_turn(target.url)
            try:
                decision = check_robots(session, target.url)
                fetched = (
                    fetch_document(session, target.url, wait_until="commit")
                    if decision.allowed
                    else None
                )
            finally:
                pacer.finished(target.url)
            check = TargetCheck(
                url=target.url,
                category=target.category,
                dns=f"{dns.address}",
                robots=decision.reason,
                http_status=fetched.status if fetched else None,
                final_host=urlsplit(fetched.final_url).hostname
                if fetched and fetched.final_url
                else None,
                problem=fetched.error if fetched else None,
            )
        checks.append(check)
        progress(f"{target.url}: dns={check.dns} robots={check.robots} http={check.http_status}")
    return checks
