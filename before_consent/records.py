"""Turn what the browser saw into the minimal records we keep.

Values never leave this module: cookie values, storage values and URL parameter values are
read only to drop them, except a consent signal we know how to interpret.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from before_consent.signals import google_consent_signal, known_cookie_owner
from before_consent.trackers import TrackerList, is_third_party, registrable_domain, tracker_match

MAX_PATH_SEGMENTS = 2
MAX_PARAM_NAMES = 40
MAX_NAME_LENGTH = 100
_ID_LIKE = re.compile(r"\d{4,}|[0-9a-f]{16,}|[=;,]", re.IGNORECASE)


@dataclass(frozen=True)
class RequestRecord:
    started_ms: int
    host: str
    path: str
    resource_type: str
    is_third_party: bool
    blocked_reason: str | None
    param_names: str
    consent_signal: str | None
    consent_denied: bool
    tracker_domain: str | None
    tracker_owner: str | None
    tracker_category: str | None


@dataclass(frozen=True)
class CookieRecord:
    name: str
    domain: str
    expires_unix: float | None
    secure: bool
    http_only: bool
    same_site: str
    is_third_party: bool
    tracker_owner: str | None
    tracker_source: str | None


@dataclass(frozen=True)
class StorageKeyRecord:
    storage: str
    origin_host: str
    key: str
    is_third_party: bool
    tracker_owner: str | None


@dataclass
class VisitResult:
    url: str
    status: str
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat("T", "seconds"))
    started_unix: float = field(default_factory=time.time)
    error: str | None = None
    final_host: str | None = None
    http_status: int | None = None
    load_ms: int | None = None
    cmp: str | None = None
    requests: list[RequestRecord] = field(default_factory=list)
    cookies: list[CookieRecord] = field(default_factory=list)
    storage_keys: list[StorageKeyRecord] = field(default_factory=list)


def trimmed_path(path: str) -> str:
    segments = [s for s in path.split("/") if s][:MAX_PATH_SEGMENTS]
    kept = ["{id}" if len(s) > 32 or _ID_LIKE.search(s) else s for s in segments]
    return "/" + "/".join(kept)


def request_record(
    url: str,
    resource_type: str,
    started_ms: int,
    site_domain: str,
    trackers: TrackerList,
    blocked_reason: str | None = None,
) -> RequestRecord:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    params = parse_qs(parts.query, keep_blank_values=True)
    names = sorted({name[:MAX_NAME_LENGTH] for name in params})[:MAX_PARAM_NAMES]
    match = tracker_match(host, trackers)
    third_party = is_third_party(host, site_domain)
    # gcs is Google's parameter; on anyone else's request it could mean something else.
    signal = google_consent_signal(params) if match and match.owner == "Google" else None
    return RequestRecord(
        started_ms=started_ms,
        host=host,
        path=trimmed_path(parts.path),
        resource_type=resource_type,
        is_third_party=third_party,
        blocked_reason=blocked_reason,
        param_names=",".join(names),
        consent_signal=signal.text if signal else None,
        consent_denied=bool(signal and signal.denied),
        tracker_domain=match.domain if match and third_party else None,
        tracker_owner=match.owner if match and third_party else None,
        tracker_category=match.category if match and third_party else None,
    )


def cookie_record(cookie: dict, site_domain: str, trackers: TrackerList) -> CookieRecord:
    domain = cookie["domain"].lstrip(".").lower()
    third_party = is_third_party(domain, site_domain)
    match = tracker_match(domain, trackers) if third_party else None
    owner, source = (match.owner, "list") if match else (None, None)
    if owner is None and (named := known_cookie_owner(cookie["name"])):
        owner, source = named, "cookie_name"
    expires = cookie.get("expires", -1)
    return CookieRecord(
        name=cookie["name"][:MAX_NAME_LENGTH],
        domain=domain,
        expires_unix=float(expires) if expires and expires > 0 else None,
        secure=bool(cookie.get("secure")),
        http_only=bool(cookie.get("httpOnly")),
        same_site=str(cookie.get("sameSite", "")),
        is_third_party=third_party,
        tracker_owner=owner,
        tracker_source=source,
    )


def storage_key_record(
    storage: str, origin_host: str, key: str, site_domain: str, trackers: TrackerList
) -> StorageKeyRecord:
    third_party = is_third_party(origin_host, site_domain)
    match = tracker_match(origin_host, trackers) if third_party else None
    return StorageKeyRecord(
        storage=storage,
        origin_host=origin_host.lower(),
        key=key[:MAX_NAME_LENGTH],
        is_third_party=third_party,
        tracker_owner=match.owner if match else None,
    )


def site_domain_of(url: str) -> str:
    return registrable_domain(urlsplit(url).hostname or "")
