"""Aggregated CSV exports and the static HTML report. Every figure comes from queries/*.sql."""

import csv
import sqlite3
from pathlib import Path

from before_consent import store
from before_consent.config import Settings

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
        path = out_dir / f"{name}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            if rows:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows({k: _csv_safe(v) for k, v in row.items()} for row in rows)
        written.append(path)
    return written
