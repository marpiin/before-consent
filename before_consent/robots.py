"""robots.txt decisions following RFC 9309, section 2.3.1."""

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

# RFC 9309 section 2.5 asks parsers to read at least 500 KiB.
MAX_ROBOTS_BYTES = 500 * 1024


@dataclass(frozen=True)
class RobotsDecision:
    allowed: bool
    reason: str


def robots_url(page_url: str) -> str:
    parts = urlsplit(page_url)
    return urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))


def robots_decision(
    status: int | None, body: str, product_token: str, page_url: str
) -> RobotsDecision:
    """Decide whether page_url may be fetched. status is None when robots.txt was unreachable."""
    if status is None:
        return RobotsDecision(False, "robots.txt unreachable, treated as disallow")
    if 500 <= status:
        return RobotsDecision(False, f"robots.txt returned {status}, treated as disallow")
    if 400 <= status:
        return RobotsDecision(True, f"robots.txt returned {status}, treated as allow")
    if not 200 <= status < 300:
        return RobotsDecision(False, f"robots.txt returned unexpected status {status}")
    parser = RobotFileParser()
    parser.parse(body[:MAX_ROBOTS_BYTES].splitlines())
    if parser.can_fetch(product_token, page_url):
        return RobotsDecision(True, "allowed by robots.txt")
    return RobotsDecision(False, "disallowed by robots.txt")
