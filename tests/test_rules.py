import pytest

from before_consent.config import ConfigError, Settings, check_politeness, require_contact
from before_consent.netguard import address_verdict, url_verdict
from before_consent.pacing import Pacer, rotation
from before_consent.records import trimmed_path
from before_consent.robots import robots_decision
from before_consent.signals import google_consent_signal, known_cookie_owner


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
    ],
)
def test_non_public_addresses_are_refused(address):
    assert address_verdict(address).allowed is False


def test_public_address_is_allowed_and_allow_local_does_not_open_link_local():
    assert address_verdict("8.8.8.8").allowed is True
    assert address_verdict("127.0.0.1", allow_local=True).allowed is True
    assert address_verdict("169.254.169.254", allow_local=True).allowed is False


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://site.example/", "javascript:1"])
def test_only_http_and_https_urls(url):
    assert url_verdict(url, resolve=lambda host: ["8.8.8.8"]).allowed is False


def test_one_private_answer_is_enough_to_refuse_a_host():
    verdict = url_verdict("https://mixed.example/", resolve=lambda host: ["8.8.8.8", "10.0.0.1"])
    assert verdict.allowed is False


@pytest.mark.parametrize(
    ("status", "allowed"), [(None, False), (500, False), (503, False), (404, True), (403, True)]
)
def test_robots_status_handling_follows_rfc_9309(status, allowed):
    assert robots_decision(status, "", "before-consent-audit", "https://a.example/").allowed is (
        allowed
    )


def test_robots_rules_for_our_product_token():
    body = "User-agent: before-consent-audit\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    decision = robots_decision(200, body, "before-consent-audit", "https://a.example/")
    assert decision.allowed is False


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/g/collect", "/g/collect"),
        ("/pagead/viewthroughconversion/123456789/", "/pagead/viewthroughconversion"),
        ("/u/12345/profile", "/u/{id}"),
        ("/ddm/activity/src=123;type=x", "/ddm/activity"),
        ("/a;b=1/x", "/{id}/x"),
        ("", "/"),
    ],
)
def test_trimmed_path(path, expected):
    assert trimmed_path(path) == expected


@pytest.mark.parametrize(
    ("gcs", "text", "denied"),
    [
        ("G100", "gcs ad_storage=denied analytics_storage=denied", True),
        ("G111", "gcs ad_storage=granted analytics_storage=granted", False),
        ("G101", "gcs ad_storage=denied analytics_storage=granted", False),
        ("G1--", "gcs ad_storage=not_set analytics_storage=not_set", False),
        ("X9", "gcs=unrecognized", False),
    ],
)
def test_gcs_interpretation(gcs, text, denied):
    signal = google_consent_signal({"gcs": [gcs]})
    assert (signal.text, signal.denied) == (text, denied)


def test_documented_cookie_names_only():
    assert known_cookie_owner("_ga") == "Google"
    assert known_cookie_owner("_ga_ABC123") == "Google"
    assert known_cookie_owner("_fbp") == "Meta"
    assert known_cookie_owner("_gid") is None


def test_politeness_floors_cannot_be_lowered():
    with pytest.raises(ConfigError):
        check_politeness(Settings(gap_seconds=1))
    with pytest.raises(ConfigError):
        check_politeness(Settings(same_site_gap_seconds=10))
    with pytest.raises(ConfigError):
        check_politeness(Settings(visit_timeout_seconds=60))


@pytest.mark.parametrize("contact", ["", "  ", "someone@example.com", "https://example.org"])
def test_missing_or_placeholder_contact_refuses_real_visits(contact):
    with pytest.raises(ConfigError):
        require_contact(Settings(contact=contact))


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_rotation_keeps_30_seconds_between_visits_to_the_same_site():
    clock = FakeClock()
    pacer = Pacer(gap_seconds=5, same_site_gap_seconds=30, clock=clock, sleep=clock.sleep)
    starts: list[tuple[str, float]] = []
    ends: dict[str, float] = {}
    for site, _round in rotation(["a", "b", "c"], 3):
        pacer.wait_turn(site)
        if site in ends:
            assert clock.now - ends[site] >= 30
        if starts:
            assert clock.now - max(ends.values()) >= 5
        starts.append((site, clock.now))
        clock.now += 2  # the visit itself
        ends[site] = clock.now
        pacer.finished(site)

    assert [s for s, _ in starts] == ["a", "b", "c"] * 3
    # With three sites the 5 s gap alone would allow a=0, 7, 14; the 30 s rule must win.
    assert starts[3] == ("a", 32.0)


def test_single_site_waits_the_full_same_site_gap():
    clock = FakeClock()
    pacer = Pacer(gap_seconds=5, same_site_gap_seconds=30, clock=clock, sleep=clock.sleep)
    pacer.wait_turn("a")
    pacer.finished("a")
    assert pacer.wait_turn("a") == 30
