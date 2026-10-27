"""Every query in queries/ against the seeded database, whose contents are described in seed.py."""

import pytest
from seed import seed

from before_consent import store
from before_consent.report import site_labels


@pytest.fixture(scope="module")
def db(fixture_trackers):
    connection = store.connect(":memory:")
    run_id = seed(connection, fixture_trackers)
    yield connection, run_id
    connection.close()


def q(db, name, **params):
    connection, run_id = db
    return store.run_query(connection, name, run_id=run_id, min_sites=1, **params)


def test_every_query_starts_with_the_question_it_answers():
    for name in store.query_names():
        question = store.query_question(name)
        assert question.endswith("?"), name
        assert len(question.splitlines()) == 1


def test_latest_run(db):
    assert q(db, "latest_run") == [{"run_id": db[1]}]


def test_run_summary(db):
    (row,) = q(db, "run_summary")
    assert row["country"] == "ES"
    assert (row["visits"], row["ok_visits"], row["failed_visits"], row["skipped_visits"]) == (
        18,
        14,
        1,
        3,
    )
    assert (row["listed_sites"], row["measured_sites"]) == (6, 5)


def test_headline(db):
    (row,) = q(db, "headline")
    assert row == {
        "sites": 5,
        "sites_with_incident": 3,
        "sites_tracker_request": 3,
        "sites_storage": 1,
        "sites_consent_aware": 1,
        "sites_no_cmp": 2,
        "pct_incident": 60.0,
        "pct_tracker_request": 60.0,
        "pct_storage": 20.0,
    }


def test_findings_by_category_respects_the_minimum(db):
    rows = q(db, "findings_by_category")
    assert [
        (r["category"], r["sites"], r["sites_with_incident"], r["pct_incident"]) for r in rows
    ] == [
        ("gov", 1, 1, 100.0),
        ("news", 2, 1, 50.0),
        ("shop", 2, 1, 50.0),
    ]
    connection, run_id = db
    two = store.run_query(connection, "findings_by_category", run_id=run_id, min_sites=2)
    assert [r["category"] for r in two] == ["news", "shop"]


def test_tracker_prevalence(db):
    rows = q(db, "tracker_prevalence")
    assert [(r["tracker_domain"], r["sites"], r["pct_sites"]) for r in rows] == [
        ("tracker.example", 3, 60.0),
        ("google.tracker.example", 1, 20.0),
    ]
    google = rows[1]
    assert (google["requests_without_denied_signal"], google["requests_with_denied_signal"]) == (
        0,
        3,
    )


def test_trackers_by_owner(db):
    rows = q(db, "trackers_by_owner")
    # Tracker Inc: news-a 2 x 3 rounds, shop-a 1, gov-b 1 x 2 rounds.
    assert [(r["tracker_owner"], r["sites"], r["requests"]) for r in rows] == [
        ("Tracker Inc", 3, 9),
        ("Google", 1, 3),
    ]


def test_cookie_lifetime(db):
    assert q(db, "cookie_lifetime") == [
        {"lifetime": "1 year or more", "cookies": 3, "cookie_names": 1, "sites": 1}
    ]


def test_consistency(db):
    rows = {r["kind"]: r for r in q(db, "consistency")}
    tracker = rows["tracker_request_before_choice"]
    # news-a and gov-b in all their ok rounds, shop-a in one of three.
    assert (tracker["sites"], tracker["sites_every_round"], tracker["sites_some_rounds"]) == (
        3,
        2,
        1,
    )
    assert rows["storage_before_choice"]["pct_every_round"] == 100.0


def test_site_summary(db):
    rows = {r["url"]: r for r in q(db, "site_summary")}
    assert rows["https://gov-a.example/"]["last_problem"] == "disallowed by robots.txt"
    assert rows["https://gov-b.example/"]["ok_visits"] == 2
    assert rows["https://news-a.example/"]["finding_kinds"] == (
        "no_cmp_detected storage_before_choice tracker_request_before_choice"
    )
    assert rows["https://shop-b.example/"]["finding_kinds"] is None


def test_representative_visit_and_its_log(db):
    (visit,) = q(db, "representative_visit")
    # Nine visits have tracker requests: six with one, three (news-a) with two.
    assert visit["tracker_requests"] == 1
    log = q(db, "visit_requests", visit_id=visit["visit_id"])
    assert [r["started_ms"] for r in log] == sorted(r["started_ms"] for r in log)
    assert log[0]["resource_type"] == "document"


def test_pseudonyms_are_stable_and_hide_urls(db):
    connection, _ = db
    labels = site_labels(connection, show_site_names=False)
    assert sorted(labels.values()) == [
        "gov-01",
        "gov-02",
        "news-01",
        "news-02",
        "shop-01",
        "shop-02",
    ]
    assert site_labels(connection, show_site_names=False) == labels
