"""Audit the demo page before any choice and after clicking Accept, without network access.

The demo is served from 127.0.0.1, which is why the guard runs with allow_local. Google's
script is replaced by gtag-stub.js and the analytics pings are answered locally with 204.

    python demo/audit_demo.py
"""

import functools
import socket
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import Page, Playwright, Route, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from before_consent.config import Settings  # noqa: E402
from before_consent.netguard import GuardProxy  # noqa: E402
from before_consent.records import VisitResult  # noqa: E402
from before_consent.trackers import parse_disconnect  # noqa: E402
from before_consent.visit import BrowserSession, launch_browser, visit_site  # noqa: E402

DEMO_DIR = Path(__file__).resolve().parent
GTAG_URL = "https://www.googletagmanager.com/gtag/js"
COLLECT_URL = "https://www.google-analytics.com/g/collect"
# The one Disconnect entry the demo touches, so the audit does not need the downloaded list.
DEMO_TRACKERS = parse_disconnect(
    {"categories": {"Analytics": [{"Google": {"https://google.com/": ["google-analytics.com"]}}]}}
)
SETTINGS = Settings(settle_seconds=1.0, visit_timeout_seconds=20)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        return


def offline_resolve(host: str) -> list[str]:
    raise socket.gaierror(f"the demo audit is offline, refusing to resolve {host}")


def stub_google(route: Route) -> None:
    url = route.request.url
    if url.startswith(GTAG_URL):
        route.fulfill(
            status=200,
            content_type="text/javascript",
            body=(DEMO_DIR / "gtag-stub.js").read_text(encoding="utf-8"),
        )
    elif url.startswith(COLLECT_URL):
        route.fulfill(status=204, body="")
    else:
        route.fallback()


def click_accept(page: Page) -> None:
    page.click("#accept")
    page.wait_for_timeout(1000)


def audit_demo(playwright: Playwright, channel: str = "chromium") -> dict[str, VisitResult]:
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(DEMO_DIR))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    proxy = GuardProxy(resolve=offline_resolve, allow_local=True).start()
    browser = launch_browser(playwright, channel, proxy)
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
    try:
        session = BrowserSession(
            browser, proxy, SETTINGS, DEMO_TRACKERS, "demo-audit", transport=stub_google
        )
        return {
            "before any choice": visit_site(session, url),
            "after Accept": visit_site(session, url, after_load=click_accept),
        }
    finally:
        browser.close()
        proxy.stop()
        server.shutdown()
        server.server_close()


def describe(result: VisitResult) -> list[str]:
    pings = [r for r in result.requests if r.tracker_owner]
    cookies = [c for c in result.cookies if c.tracker_owner]
    lines = [f"  status: {result.status}"]
    lines += [f"  request {r.host}{r.path}: {r.consent_signal}" for r in pings]
    lines += [f"  cookie {c.name} on {c.domain} ({c.tracker_source})" for c in cookies]
    if not cookies:
        lines.append("  no tracker cookies")
    return lines


def main() -> None:
    with sync_playwright() as playwright:
        results = audit_demo(playwright)
    for label, result in results.items():
        print(label)
        print("\n".join(describe(result)))


if __name__ == "__main__":
    main()
