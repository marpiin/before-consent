"""SQLite storage and the named queries in queries/*.sql."""

import sqlite3
from dataclasses import astuple
from datetime import UTC, datetime
from pathlib import Path

from before_consent import __version__
from before_consent.lists import ListSnapshot
from before_consent.records import VisitResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "schema.sql"
QUERIES_DIR = PROJECT_ROOT / "queries"


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return connection


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def start_run(
    connection: sqlite3.Connection,
    country: str,
    browser_channel: str,
    browser_version: str,
    snapshot: ListSnapshot,
    config_sha256: str,
    note: str | None = None,
) -> int:
    cursor = connection.execute(
        "INSERT INTO run (started_at, country, tool_version, browser_channel, browser_version,"
        " list_source, list_sha256, list_fetched_at, config_sha256, note)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            _now(),
            country,
            __version__,
            browser_channel,
            browser_version,
            snapshot.source_url,
            snapshot.sha256,
            snapshot.fetched_at,
            config_sha256,
            note,
        ),
    )
    connection.commit()
    return cursor.lastrowid


def finish_run(connection: sqlite3.Connection, run_id: int) -> None:
    connection.execute("UPDATE run SET finished_at = ? WHERE run_id = ?", (_now(), run_id))
    connection.commit()


def site_id(connection: sqlite3.Connection, url: str, category: str) -> int:
    connection.execute(
        "INSERT INTO site (url, category) VALUES (?, ?)"
        " ON CONFLICT (url) DO UPDATE SET category = excluded.category",
        (url, category),
    )
    row = connection.execute("SELECT site_id FROM site WHERE url = ?", (url,)).fetchone()
    return row["site_id"]


def save_visit(
    connection: sqlite3.Connection, run_id: int, site: int, round_: int, result: VisitResult
) -> int:
    cursor = connection.execute(
        "INSERT INTO visit (run_id, site_id, round, started_at, started_unix, status, error,"
        " final_host, http_status, load_ms, cmp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            site,
            round_,
            result.started_at,
            result.started_unix,
            result.status,
            result.error,
            result.final_host,
            result.http_status,
            result.load_ms,
            result.cmp,
        ),
    )
    visit_id = cursor.lastrowid
    connection.executemany(
        "INSERT INTO request_log (visit_id, started_ms, host, path, resource_type,"
        " is_third_party, blocked_reason, param_names, consent_signal, consent_denied,"
        " tracker_domain, tracker_owner, tracker_category)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(visit_id, *astuple(r)) for r in result.requests],
    )
    connection.executemany(
        "INSERT INTO cookie (visit_id, name, domain, expires_unix, secure, http_only, same_site,"
        " is_third_party, tracker_owner, tracker_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(visit_id, *astuple(c)) for c in result.cookies],
    )
    connection.executemany(
        "INSERT INTO storage_key (visit_id, storage, origin_host, key, is_third_party,"
        " tracker_owner) VALUES (?, ?, ?, ?, ?, ?)",
        [(visit_id, *astuple(s)) for s in result.storage_keys],
    )
    connection.commit()
    return visit_id


def query_names() -> list[str]:
    return sorted(p.stem for p in QUERIES_DIR.glob("*.sql"))


def query_question(name: str) -> str:
    first_line = (QUERIES_DIR / f"{name}.sql").read_text(encoding="utf-8").splitlines()[0]
    return first_line.removeprefix("--").strip()


def run_query(connection: sqlite3.Connection, name: str, **params: object) -> list[dict]:
    if name not in query_names():
        raise ValueError(f"no query named {name!r} in {QUERIES_DIR}")
    sql = (QUERIES_DIR / f"{name}.sql").read_text(encoding="utf-8")
    return [dict(row) for row in connection.execute(sql, params)]
