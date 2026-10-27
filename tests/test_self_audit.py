"""The report must pass its own audit: no third parties, no cookies, no storage."""

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import CHANNEL, TEST_SETTINGS, offline_resolve
from seed import seed

from before_consent import store
from before_consent.config import Settings
from before_consent.netguard import GuardProxy
from before_consent.report import build_report
from before_consent.visit import BrowserSession, launch_browser, visit_site


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        return


@pytest.fixture
def served_report(tmp_path, fixture_trackers):
    connection = store.connect(":memory:")
    run_id = seed(connection, fixture_trackers)
    build_report(connection, run_id, Settings(min_sites_per_category=1), tmp_path)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(tmp_path))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    server.shutdown()
    server.server_close()


def test_generated_report_contacts_no_third_party_and_sets_no_cookie(
    served_report, fixture_trackers, playwright
):
    # --allow-local exists for this: the report is served from loopback.
    proxy = GuardProxy(resolve=offline_resolve, allow_local=True).start()
    browser = launch_browser(playwright, CHANNEL, proxy)
    try:
        session = BrowserSession(browser, proxy, TEST_SETTINGS, fixture_trackers, "audit")
        result = visit_site(session, served_report)
    finally:
        browser.close()
        proxy.stop()

    assert result.status == "ok", result.error
    assert {r.host for r in result.requests} == {"127.0.0.1"}
    assert [r for r in result.requests if r.is_third_party] == []
    assert [r for r in result.requests if r.blocked_reason] == []
    assert result.cookies == []
    assert result.storage_keys == []
    assert result.cmp is None
