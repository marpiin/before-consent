import pytest
from conftest import FakeWeb
from seed import SNAPSHOT, seed

from before_consent import store
from before_consent.visit import visit_site


@pytest.fixture
def seeded(fixture_trackers):
    connection = store.connect(":memory:")
    run_id = seed(connection, fixture_trackers)
    yield connection, run_id
    connection.close()


def kinds_by_site(connection, run_id):
    rows = connection.execute(
        "SELECT s.url, f.kind FROM site_finding f JOIN site s USING (site_id)"
        " WHERE f.run_id = ? ORDER BY s.url, f.kind",
        (run_id,),
    )
    found: dict[str, list[str]] = {}
    for url, kind in rows:
        found.setdefault(url.split("//")[1].split(".")[0], []).append(kind)
    return found


def test_each_site_gets_the_expected_categories(seeded):
    connection, run_id = seeded
    assert kinds_by_site(connection, run_id) == {
        "gov-b": ["no_cmp_detected", "tracker_request_before_choice"],
        "news-a": ["no_cmp_detected", "storage_before_choice", "tracker_request_before_choice"],
        "news-b": ["consent_aware_request"],
        "shop-a": ["tracker_request_before_choice"],
    }


def test_blocked_requests_are_logged_but_not_third_party_contact(seeded):
    connection, _ = seeded
    logged = connection.execute(
        "SELECT COUNT(*) FROM request_log WHERE host = '127.0.0.1' AND blocked_reason IS NOT NULL"
    ).fetchone()[0]
    contact = connection.execute(
        "SELECT COUNT(*) FROM third_party_contact WHERE host = '127.0.0.1'"
    ).fetchone()[0]
    assert (logged, contact) == (2, 0)


def test_consent_aware_requests_are_not_incidents(seeded):
    connection, _ = seeded
    kinds = {row[0] for row in connection.execute("SELECT DISTINCT kind FROM incident")}
    assert "consent_aware_request" not in kinds


def test_no_values_are_stored(seeded):
    connection, _ = seeded
    for table in ("cookie", "storage_key", "request_log"):
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        assert "value" not in columns
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM request_log WHERE param_names LIKE '%=%'"
        ).fetchone()[0]
        == 0
    )


def test_fixture_visit_end_to_end_is_classified_consent_aware(make_session):
    ping = "https://google.tracker.example/g/collect?v=2&gcs=G100"
    web = FakeWeb(
        pages={
            "https://site.example/": (
                200,
                "text/html",
                f'<script>window.__tcfapi = function () {{}};</script><img src="{ping}">',
            ),
            ping: (204, "text/plain", ""),
        }
    )
    result = visit_site(make_session(web), "https://site.example/")
    connection = store.connect(":memory:")

    run_id = store.start_run(connection, "ES", "chromium", "1", SNAPSHOT, "c" * 64)
    site = store.site_id(connection, "https://site.example/", "news")
    store.save_visit(connection, run_id, site, 1, result)

    assert result.cmp == "tcf"
    kinds = [row[0] for row in connection.execute("SELECT kind FROM finding")]
    assert kinds == ["consent_aware_request"]
