import os
import socket
from dataclasses import dataclass, field

import pytest
from playwright.sync_api import Route, sync_playwright

from before_consent.config import Settings
from before_consent.netguard import GuardProxy
from before_consent.trackers import TrackerList, parse_disconnect
from before_consent.visit import BrowserSession, launch_browser

CHANNEL = os.environ.get("BEFORE_CONSENT_TEST_CHANNEL", "chromium")
TEST_SETTINGS = Settings(settle_seconds=0.5, visit_timeout_seconds=20)
TEST_USER_AGENT_CONTACT = "https://tests.invalid/before-consent"


def offline_resolve(host: str) -> list[str]:
    # Tests must never reach the network: any name that gets past the fixtures fails here.
    raise socket.gaierror(f"offline test, refusing to resolve {host}")


FIXTURE_LIST = {
    "categories": {
        "Analytics": [
            {"Google": {"https://google.example/": ["google.tracker.example"]}},
            {"Tracker Inc": {"https://tracker.example/": ["tracker.example"]}},
        ],
        "ConsentManagers": [{"CMP Co": {"https://cmp.example/": ["cmp.example"]}}],
    }
}


@pytest.fixture(scope="session")
def fixture_trackers() -> TrackerList:
    return parse_disconnect(FIXTURE_LIST)


@dataclass
class FakeWeb:
    """Serves fixture responses by URL; anything else falls through to the guard proxy."""

    pages: dict[str, tuple[int, str, str]] = field(default_factory=dict)
    redirects: dict[str, str] = field(default_factory=dict)
    hits: list[str] = field(default_factory=list)

    def __call__(self, route: Route) -> None:
        url = route.request.url
        self.hits.append(url)
        if url in self.redirects:
            route.fulfill(status=302, headers={"location": self.redirects[url]})
        elif url in self.pages:
            status, content_type, body = self.pages[url]
            route.fulfill(status=status, content_type=content_type, body=body)
        else:
            route.fallback()


@pytest.fixture(scope="session")
def playwright():
    with sync_playwright() as instance:
        yield instance


@pytest.fixture(scope="session")
def browser_and_proxy(playwright):
    proxy = GuardProxy(resolve=offline_resolve).start()
    browser = launch_browser(playwright, CHANNEL, proxy)
    yield browser, proxy
    browser.close()
    proxy.stop()


@pytest.fixture
def make_session(browser_and_proxy, fixture_trackers):
    browser, proxy = browser_and_proxy

    def build(web: FakeWeb, settings: Settings = TEST_SETTINGS) -> BrowserSession:
        return BrowserSession(
            browser=browser,
            proxy=proxy,
            settings=settings,
            trackers=fixture_trackers,
            user_agent=f"test-agent before-consent-audit/0 (+{TEST_USER_AGENT_CONTACT})",
            transport=web,
        )

    return build
