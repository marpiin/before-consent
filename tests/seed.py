"""A small database with known contents, used by the query and report tests.

Sites and what their successful visits contain:
  news-a  news  3 ok    two Tracker Inc requests and a 2-year _ga cookie each, no CMP
  news-b  news  3 ok    one Google ping with gcs=G100 each, TCF CMP
  shop-a  shop  3 ok    one Tracker Inc request in round 1 only, Didomi CMP
  shop-b  shop  3 ok    first-party requests only
  gov-a   gov   3 skipped by robots.txt
  gov-b   gov   1 failed, 2 ok with one Tracker Inc request and one blocked request to 127.0.0.1
"""

import sqlite3

from before_consent import store
from before_consent.lists import ListSnapshot
from before_consent.records import VisitResult, cookie_record, request_record
from before_consent.trackers import TrackerList

SNAPSHOT = ListSnapshot("https://list.invalid/services.json", "test", "2026-01-01", "0" * 64, 1)
TWO_YEARS = 2 * 365 * 86400
START = 1_800_000_000.0


def _visit(url: str, status: str, round_: int, trackers: TrackerList, **content) -> VisitResult:
    domain = url.split("//")[1].strip("/")
    result = VisitResult(
        url=url,
        status=status,
        started_at="2026-01-01T10:00:00+00:00",
        started_unix=START + round_,
    )
    if status != "ok":
        result.error = content.get("error", "net::ERR_TIMED_OUT")
        return result
    result.cmp = content.get("cmp")
    result.load_ms = 900
    result.requests.append(request_record(url, "document", 0, domain, trackers))
    for i, (request_url, blocked) in enumerate(content.get("requests", [])):
        result.requests.append(
            request_record(request_url, "image", 100 * (i + 1), domain, trackers, blocked)
        )
    for name in content.get("cookies", []):
        cookie = {"name": name, "domain": "." + domain, "expires": START + TWO_YEARS}
        result.cookies.append(cookie_record(cookie, domain, trackers))
    return result


def seed(connection: sqlite3.Connection, trackers: TrackerList) -> int:
    run_id = store.start_run(connection, "ES", "chromium", "1.0", SNAPSHOT, "c" * 64)
    tracker_px = ("https://tracker.example/px.gif?ev=view", None)
    tracker_js = ("https://tracker.example/t.js", None)
    google_denied = ("https://google.tracker.example/g/collect?v=2&gcs=G100", None)
    loopback = ("http://127.0.0.1:8080/x", "non-public address 127.0.0.1")

    plan = {
        ("https://news-a.example/", "news"): lambda r: _visit(
            "https://news-a.example/",
            "ok",
            r,
            trackers,
            requests=[tracker_js, tracker_px],
            cookies=["_ga"],
        ),
        ("https://news-b.example/", "news"): lambda r: _visit(
            "https://news-b.example/", "ok", r, trackers, requests=[google_denied], cmp="tcf"
        ),
        ("https://shop-a.example/", "shop"): lambda r: _visit(
            "https://shop-a.example/",
            "ok",
            r,
            trackers,
            requests=[tracker_px] if r == 1 else [],
            cmp="didomi",
        ),
        ("https://shop-b.example/", "shop"): lambda r: _visit(
            "https://shop-b.example/", "ok", r, trackers
        ),
        ("https://gov-a.example/", "gov"): lambda r: _visit(
            "https://gov-a.example/",
            "skipped_robots",
            r,
            trackers,
            error="disallowed by robots.txt",
        ),
        ("https://gov-b.example/", "gov"): lambda r: _visit(
            "https://gov-b.example/",
            "failed" if r == 1 else "ok",
            r,
            trackers,
            requests=[tracker_px, loopback],
        ),
    }
    for round_ in (1, 2, 3):
        for (url, category), build in plan.items():
            site = store.site_id(connection, url, category)
            store.save_visit(connection, run_id, site, round_, build(round_))
    store.finish_run(connection, run_id)
    return run_id
