import socket

from conftest import FakeWeb

from before_consent.visit import check_robots, visit_site

HTML = "text/html"
SITE = "https://site.example/"


def page(body: str) -> tuple[int, str, str]:
    return (200, HTML, f"<!doctype html><html><body>{body}</body></html>")


def test_clean_page_has_no_tracker_activity(make_session):
    web = FakeWeb(
        pages={
            SITE: page('<img src="https://site.example/logo.png"><p>hello</p>'),
            "https://site.example/logo.png": (200, "image/png", ""),
        }
    )
    result = visit_site(make_session(web), SITE)

    assert result.status == "ok", result.error
    assert [r.host for r in result.requests] == ["site.example", "site.example"]
    assert not any(r.is_third_party for r in result.requests)
    assert result.cookies == []
    assert result.cmp is None


def test_tracker_request_and_ga_cookie_set_by_javascript(make_session):
    tracker_js = """
      document.cookie = "_ga=GA1.1.123456789.1700000000; max-age=63072000; path=/";
      new Image().src = "https://tracker.example/pixel.gif?uid=secret-value&ev=pageview";
    """
    web = FakeWeb(
        pages={
            SITE: page('<script src="https://tracker.example/t.js"></script>'),
            "https://tracker.example/t.js": (200, "text/javascript", tracker_js),
            "https://tracker.example/pixel.gif?uid=secret-value&ev=pageview": (
                200,
                "image/gif",
                "",
            ),
        }
    )
    result = visit_site(make_session(web), SITE)

    assert result.status == "ok", result.error
    tracked = [r for r in result.requests if r.tracker_owner]
    assert {(r.host, r.path, r.resource_type) for r in tracked} == {
        ("tracker.example", "/t.js", "script"),
        ("tracker.example", "/pixel.gif", "image"),
    }
    pixel = next(r for r in tracked if r.path == "/pixel.gif")
    assert pixel.param_names == "ev,uid"
    assert "secret-value" not in repr(result)

    (ga,) = result.cookies
    assert (ga.name, ga.domain, ga.tracker_owner, ga.tracker_source) == (
        "_ga",
        "site.example",
        "Google",
        "cookie_name",
    )
    assert ga.expires_unix is not None
    assert not hasattr(ga, "value")
    assert "123456789" not in repr(result)


def test_ping_with_denied_consent_is_interpreted(make_session):
    ping = "https://google.tracker.example/g/collect?v=2&tid=G-TEST&gcs=G100&gcd=13p3p3p3p5"
    web = FakeWeb(
        pages={
            SITE: page(f'<img src="{ping}">'),
            ping: (204, "text/plain", ""),
        }
    )
    result = visit_site(make_session(web), SITE)

    (record,) = [r for r in result.requests if r.tracker_owner]
    assert record.tracker_owner == "Google"
    assert record.consent_denied is True
    assert record.consent_signal == "gcs ad_storage=denied analytics_storage=denied"
    assert record.param_names == "gcd,gcs,tid,v"
    assert "13p3p3p3p5" not in repr(result)


def test_loopback_and_metadata_redirect_are_blocked_and_never_reached(make_session):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.5)
    port = listener.getsockname()[1]
    web = FakeWeb(
        pages={
            SITE: page(
                f'<img src="http://127.0.0.1:{port}/a.gif"><img src="https://site.example/hop">'
            )
        },
        # route() does not see redirect hops, so only the proxy can stop this one.
        redirects={"https://site.example/hop": "http://169.254.169.254/latest/meta-data/"},
    )
    try:
        result = visit_site(make_session(web), SITE)
        try:
            listener.accept()
            reached = True
        except TimeoutError:
            reached = False
    finally:
        listener.close()

    assert result.status == "ok", result.error
    assert reached is False
    blocked = {r.host: r.blocked_reason for r in result.requests if r.blocked_reason}
    assert "non-public address 127.0.0.1" in blocked["127.0.0.1"]
    assert "non-public address 169.254.169.254" in blocked["169.254.169.254"]
    sent_third_party = [r for r in result.requests if r.is_third_party and not r.blocked_reason]
    assert sent_third_party == []


def test_robots_disallow_is_detected_without_loading_the_page(make_session):
    web = FakeWeb(
        pages={
            "https://site.example/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /\n"),
            SITE: page("<p>should not be loaded</p>"),
        }
    )
    decision = check_robots(make_session(web), SITE)

    assert decision.allowed is False
    assert decision.reason == "disallowed by robots.txt"
    assert web.hits == ["https://site.example/robots.txt"]


def test_robots_server_error_means_disallow_and_404_means_allow(make_session):
    web = FakeWeb(pages={"https://site.example/robots.txt": (503, "text/plain", "")})
    assert check_robots(make_session(web), SITE).allowed is False
    web = FakeWeb(pages={"https://site.example/robots.txt": (404, "text/plain", "")})
    assert check_robots(make_session(web), SITE).allowed is True


def test_dialogs_and_popups_do_not_block_the_visit(make_session):
    web = FakeWeb(
        pages={
            SITE: page("<script>alert('hi'); window.open('https://site.example/popup');</script>"),
            "https://site.example/popup": page("<p>popup</p>"),
        }
    )
    result = visit_site(make_session(web), SITE)
    assert result.status == "ok", result.error
