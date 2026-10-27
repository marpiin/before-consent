"""Drive the browser: one fresh context per visit, no clicks, capture what loaded and stored."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, Route
from playwright.sync_api import Error as PlaywrightError

from before_consent.config import Settings, user_agent_suffix
from before_consent.netguard import GuardProxy
from before_consent.records import (
    CookieRecord,
    RequestRecord,
    StorageKeyRecord,
    cookie_record,
    request_record,
    site_domain_of,
    storage_key_record,
)
from before_consent.robots import RobotsDecision, robots_decision, robots_url
from before_consent.signals import CMP_PROBE
from before_consent.trackers import TrackerList, consent_manager_match

ROBOTS_AGENT = "before-consent-audit"
DOCUMENT_TIMEOUT_MS = 15_000
CAPTURE_MARGIN_SECONDS = 5.0
STORAGE_PROBE = """() => {
  const keys = (store) => { try { return Object.keys(store); } catch (e) { return []; } };
  return { local: keys(window.localStorage), session: keys(window.sessionStorage) };
}"""

# Tests serve fixture pages through page routes; real runs install no route at all, so the
# browser behaves as it would for a visitor (routing also turns off the HTTP cache).
Transport = Callable[[Route], None]


@dataclass
class BrowserSession:
    browser: Browser
    proxy: GuardProxy
    settings: Settings
    trackers: TrackerList
    user_agent: str
    transport: Transport | None = None


@dataclass
class VisitResult:
    url: str
    status: str
    started_at: str
    started_unix: float
    error: str | None = None
    final_host: str | None = None
    http_status: int | None = None
    load_ms: int | None = None
    cmp: str | None = None
    requests: list[RequestRecord] = field(default_factory=list)
    cookies: list[CookieRecord] = field(default_factory=list)
    storage_keys: list[StorageKeyRecord] = field(default_factory=list)


@dataclass(frozen=True)
class DocumentFetch:
    status: int | None
    body: str
    final_url: str | None
    error: str | None


def launch_browser(playwright: Playwright, channel: str, proxy: GuardProxy) -> Browser:
    return playwright.chromium.launch(
        channel=channel,
        headless=True,
        # Playwright adds --no-sandbox unless this is set.
        chromium_sandbox=True,
        proxy={"server": proxy.url},
        # WebRTC can send UDP straight to any address; keep it behind the proxy, which has no
        # UDP support, so it is effectively off.
        args=["--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
    )


def honest_user_agent(browser: Browser, contact: str) -> str:
    context = browser.new_context()
    try:
        base = context.new_page().evaluate("navigator.userAgent")
    finally:
        context.close()
    return f"{base} {user_agent_suffix(contact)}"


def new_context(session: BrowserSession, javascript: bool = True) -> BrowserContext:
    s = session.settings
    context = session.browser.new_context(
        user_agent=session.user_agent,
        locale=s.locale,
        timezone_id=s.timezone,
        viewport={"width": s.viewport_width, "height": s.viewport_height},
        ignore_https_errors=False,
        service_workers="block",
        accept_downloads=False,
        permissions=[],
        java_script_enabled=javascript,
    )
    if session.transport:
        context.route("**/*", session.transport)
    return context


def _guard_page(page: Page) -> None:
    page.on("dialog", lambda dialog: dialog.dismiss())
    page.on("popup", lambda popup: popup.close())


def fetch_document(session: BrowserSession, url: str, wait_until: str = "load") -> DocumentFetch:
    """Fetch one document with JavaScript off and every subresource refused."""
    context = new_context(session, javascript=False)
    context.route(
        "**/*",
        lambda route: (
            route.fallback()
            if route.request.resource_type == "document"
            else route.abort("blockedbyclient")
        ),
    )
    page = context.new_page()
    _guard_page(page)
    statuses: list[int] = []
    page.on(
        "response",
        lambda r: (
            statuses.append(r.status)
            if r.request.is_navigation_request() and r.frame == page.main_frame
            else None
        ),
    )
    try:
        response = page.goto(url, wait_until=wait_until, timeout=DOCUMENT_TIMEOUT_MS)
        if response is None:
            return DocumentFetch(None, "", page.url, "no response")
        body = response.text() if wait_until == "load" else ""
        return DocumentFetch(response.status, body, page.url, None)
    except PlaywrightError as error:
        # Chromium fails the navigation on an error status with an empty body, but the server
        # did answer, and for robots.txt the status is what matters.
        last_status = statuses[-1] if statuses else None
        return DocumentFetch(last_status, "", None, _first_line(error))
    finally:
        context.close()


def check_robots(session: BrowserSession, page_url: str) -> RobotsDecision:
    fetched = fetch_document(session, robots_url(page_url))
    session.proxy.take_blocked()
    return robots_decision(fetched.status, fetched.body, ROBOTS_AGENT, page_url)


def visit_site(
    session: BrowserSession, url: str, after_load: Callable[[Page], None] | None = None
) -> VisitResult:
    """Open url, wait for load plus the settle period, then capture. Never interacts.

    after_load exists only for the demo audit, which clicks its own banner to show the
    contrast. The CLI never passes it.
    """
    s = session.settings
    started = time.monotonic()
    result = VisitResult(
        url=url,
        status="failed",
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        started_unix=time.time(),
    )
    seen: list[tuple[int, str, str]] = []

    def elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    session.proxy.take_blocked()
    context = new_context(session)
    # Logged at context level so requests from popups, frames and workers are included.
    context.on("request", lambda r: seen.append((elapsed_ms(), r.url, r.resource_type)))
    page = context.new_page()
    _guard_page(page)
    page.on("websocket", lambda ws: seen.append((elapsed_ms(), ws.url, "websocket")))
    navigation_ms = (s.visit_timeout_seconds - s.settle_seconds - CAPTURE_MARGIN_SECONDS) * 1000
    try:
        response = page.goto(url, wait_until="load", timeout=navigation_ms)
        result.load_ms = elapsed_ms()
        result.http_status = response.status if response else None
        page.wait_for_timeout(s.settle_seconds * 1000)
        if after_load:
            after_load(page)
        result.final_host = urlsplit(page.url).hostname
        cmp_globals = page.evaluate(CMP_PROBE)
        storage = _storage_keys(page)
        cookies = context.cookies()
    except PlaywrightError as error:
        result.error = _first_line(error)
        return result
    finally:
        context.close()
        blocked = session.proxy.take_blocked()

    site_domain = site_domain_of(page.url)
    for started_ms, request_url, resource_type in seen:
        host = (urlsplit(request_url).hostname or "").lower()
        if urlsplit(request_url).scheme not in ("http", "https", "ws", "wss"):
            continue
        result.requests.append(
            request_record(
                request_url,
                resource_type,
                started_ms,
                site_domain,
                session.trackers,
                blocked_reason=blocked.get(host),
            )
        )
    result.cookies = [cookie_record(c, site_domain, session.trackers) for c in cookies]
    result.storage_keys = [
        storage_key_record(kind, origin, key, site_domain, session.trackers)
        for kind, origin, key in storage
    ]
    result.cmp = _cmp_label(cmp_globals, result.requests, session.trackers)
    if result.http_status is not None and result.http_status >= 400:
        result.status = "http_error"
        result.error = f"main document returned HTTP {result.http_status}"
    else:
        result.status = "ok"
    return result


def _storage_keys(page: Page) -> list[tuple[str, str, str]]:
    found = []
    for frame in page.frames:
        host = urlsplit(frame.url).hostname
        if not host:
            continue
        try:
            keys = frame.evaluate(STORAGE_PROBE)
        except PlaywrightError:
            # Frames can detach between listing and evaluation; their keys are lost, not faked.
            continue
        found += [("local", host, k) for k in keys["local"]]
        found += [("session", host, k) for k in keys["session"]]
    return sorted(set(found))


def _cmp_label(globals_found: list[str], requests: list[RequestRecord], trackers) -> str | None:
    labels = set(globals_found)
    for record in requests:
        if record.blocked_reason is None:
            match = consent_manager_match(record.host, trackers)
            if match:
                labels.add(f"request:{match.owner}")
    return ",".join(sorted(labels)) or None


def _first_line(error: Exception) -> str:
    text = str(error).strip().splitlines()
    return text[0][:300] if text else type(error).__name__
