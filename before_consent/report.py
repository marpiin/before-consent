"""Aggregated CSV exports and the static HTML report. Every figure comes from queries/*.sql."""

import csv
import sqlite3
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from before_consent import __version__, store
from before_consent.config import Settings

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Queries whose rows are aggregates and safe to publish as CSV.
EXPORTED_QUERIES = (
    "run_summary",
    "headline",
    "findings_by_category",
    "tracker_prevalence",
    "trackers_by_owner",
    "cookie_lifetime",
    "consistency",
    "site_summary",
)


def latest_run(connection: sqlite3.Connection) -> int:
    run_id = store.run_query(connection, "latest_run")[0]["run_id"]
    if run_id is None:
        raise ValueError("the database has no finished run yet; use the run command first")
    return run_id


def site_labels(connection: sqlite3.Connection, show_site_names: bool) -> dict[int, str]:
    """Map site ids to their URL, or to a stable pseudonym such as news-03."""
    rows = connection.execute("SELECT site_id, url, category FROM site ORDER BY category, url")
    labels: dict[int, str] = {}
    counters: dict[str, int] = {}
    for site_id, url, category in rows:
        counters[category] = counters.get(category, 0) + 1
        labels[site_id] = url if show_site_names else f"{category}-{counters[category]:02d}"
    return labels


def _published_rows(
    connection: sqlite3.Connection, name: str, run_id: int, settings: Settings
) -> list[dict]:
    rows = store.run_query(
        connection, name, run_id=run_id, min_sites=settings.min_sites_per_category
    )
    if name == "site_summary":
        # Same category threshold as findings_by_category, so small groups are never listed.
        shown = {
            row["category"]
            for row in _published_rows(connection, "findings_by_category", run_id, settings)
        }
        labels = site_labels(connection, settings.show_site_names)
        rows = [{**row, "url": labels[row["site_id"]]} for row in rows if row["category"] in shown]
        if not settings.show_site_names:
            for row in rows:
                row.pop("site_id")
    return rows


def _csv_safe(value: object) -> object:
    # Spreadsheet programs run cells that start with these characters as formulas.
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def export_csv(
    connection: sqlite3.Connection, run_id: int, settings: Settings, out_dir: Path
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in EXPORTED_QUERIES:
        rows = _published_rows(connection, name, run_id, settings)
        columns = store.query_columns(
            connection, name, run_id=run_id, min_sites=settings.min_sites_per_category
        )
        if name == "site_summary" and not settings.show_site_names:
            columns.remove("site_id")
        path = out_dir / f"{name}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows({k: _csv_safe(v) for k, v in row.items()} for row in rows)
        written.append(path)
    return written


def _log_kind(row: dict) -> str:
    if row["blocked_reason"]:
        return "blocked"
    if row["tracker_owner"] and row["consent_denied"]:
        return "denied"
    if row["tracker_owner"]:
        return "tracker"
    return "third" if row["is_third_party"] else "first"


def _log_rows(rows: list[dict], show_site_names: bool) -> tuple[list[dict], int]:
    """Prepare the representative visit's requests for the timeline.

    With site names hidden, first-party and non-tracker hosts are masked because they would
    name the site; tracker hosts are kept because they are the finding.
    """
    load_ms = (rows[0]["load_ms"] or 0) if rows else 0
    span = max(max((r["started_ms"] for r in rows), default=0), load_ms, 1)
    prepared = []
    for row in rows:
        kind = _log_kind(row)
        host, path = row["host"], row["path"]
        if not show_site_names and kind in ("first", "third"):
            host = "first-party host" if kind == "first" else "other third-party host"
            path = ""
        prepared.append(
            {
                **row,
                "kind": kind,
                "shown_host": host,
                "shown_path": path,
                "x": round(100 * row["started_ms"] / span, 2),
            }
        )
    return prepared, span


def build_report(
    connection: sqlite3.Connection, run_id: int, settings: Settings, out_dir: Path
) -> Path:
    def rows(name: str) -> list[dict]:
        return _published_rows(connection, name, run_id, settings)

    csv_paths = export_csv(connection, run_id, settings, out_dir / "data")
    representative = rows("representative_visit")
    log, span, site_label = [], 1, None
    if representative:
        visit = representative[0]
        requests = store.run_query(connection, "visit_requests", visit_id=visit["visit_id"])
        log, span = _log_rows(requests, settings.show_site_names)
        site_label = site_labels(connection, settings.show_site_names)[visit["site_id"]]
    all_categories = {
        r["category"]
        for r in store.run_query(connection, "findings_by_category", run_id=run_id, min_sites=1)
    }
    categories = rows("findings_by_category")
    environment = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    html = environment.get_template("report.html.j2").render(
        tool_version=__version__,
        settings=settings,
        run=rows("run_summary")[0],
        headline=rows("headline")[0],
        categories=categories,
        hidden_categories=len(all_categories) - len(categories),
        prevalence=rows("tracker_prevalence"),
        owners=rows("trackers_by_owner"),
        lifetimes=rows("cookie_lifetime"),
        consistency=rows("consistency"),
        representative=representative[0] if representative else None,
        representative_site=site_label,
        log=log,
        log_span_ms=span,
        csv_files=[p.name for p in csv_paths],
        questions={
            name: store.query_question(name, min_sites=settings.min_sites_per_category)
            for name in store.query_names()
        },
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    path.write_text(html, encoding="utf-8")
    return path
