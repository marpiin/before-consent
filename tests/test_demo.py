from audit_demo import audit_demo
from conftest import CHANNEL
from seed import SNAPSHOT

from before_consent import store


def test_demo_sends_only_denied_pings_before_a_choice_and_sets_ga_after_accept(playwright):
    results = audit_demo(playwright, CHANNEL)
    before, after = results["before any choice"], results["after Accept"]

    assert before.status == after.status == "ok"
    assert [r.consent_signal for r in before.requests if r.tracker_owner] == [
        "gcs ad_storage=denied analytics_storage=denied"
    ]
    assert [c for c in before.cookies if c.tracker_owner] == []
    assert [r for r in before.requests if r.blocked_reason] == []

    assert [r.consent_signal for r in after.requests if r.tracker_owner][-1] == (
        "gcs ad_storage=granted analytics_storage=granted"
    )
    assert [c.name for c in after.cookies if c.tracker_owner] == ["_ga"]

    connection = store.connect(":memory:")
    run_id = store.start_run(connection, "ES", CHANNEL, "1", SNAPSHOT, "c" * 64)
    site = store.site_id(connection, "http://127.0.0.1/", "demo")
    store.save_visit(connection, run_id, site, 1, before)
    kinds = sorted(row[0] for row in connection.execute("SELECT kind FROM finding"))
    # The demo's hand-made banner is not a CMP the tool can recognise, so it is reported as
    # not detected: the limitation docs/method.md describes, shown on our own page.
    assert kinds == ["consent_aware_request", "no_cmp_detected"]
