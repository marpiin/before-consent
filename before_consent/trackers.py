"""Tracker list loading and domain matching."""

import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path

import tldextract

# No disk cache and no network: tldextract uses the public suffix snapshot it ships with.
_extract = tldextract.TLDExtract(cache_dir=None, suffix_list_urls=(), fallback_to_snapshot=True)

# Disconnect categories we count as tracking, in priority order for domains listed under
# several. Content, Email, EmailAggressive and Anti-fraud are left out on purpose; see
# docs/method.md.
TRACKER_CATEGORIES = (
    "Advertising",
    "Analytics",
    "Social",
    "FingerprintingInvasive",
    "FingerprintingGeneral",
    "Cryptomining",
)
CMP_CATEGORY = "ConsentManagers"


@dataclass(frozen=True)
class TrackerMatch:
    domain: str
    owner: str
    category: str


@dataclass(frozen=True)
class TrackerList:
    trackers: dict[str, TrackerMatch]
    consent_managers: dict[str, TrackerMatch]


def registrable_domain(host: str) -> str:
    host = host.lower().strip("[]").rstrip(".")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    parts = _extract(host)
    return parts.top_domain_under_public_suffix or host


def load_disconnect(path: Path) -> TrackerList:
    data = json.loads(path.read_text(encoding="utf-8"))
    return parse_disconnect(data)


def parse_disconnect(data: dict) -> TrackerList:
    trackers: dict[str, TrackerMatch] = {}
    consent_managers: dict[str, TrackerMatch] = {}
    categories = data["categories"]
    for category in (*TRACKER_CATEGORIES, CMP_CATEGORY):
        target = consent_managers if category == CMP_CATEGORY else trackers
        for entry in categories.get(category, []):
            for owner, sites in entry.items():
                for domains in sites.values():
                    # Besides url -> [domains], entries carry flags like "performance": "true".
                    if not isinstance(domains, list):
                        continue
                    for domain in domains:
                        domain = domain.lower()
                        target.setdefault(domain, TrackerMatch(domain, owner, category))
    return TrackerList(trackers, consent_managers)


def _lookup(host: str, table: dict[str, TrackerMatch]) -> TrackerMatch | None:
    labels = host.lower().rstrip(".").split(".")
    for start in range(len(labels) - 1):
        match = table.get(".".join(labels[start:]))
        if match:
            return match
    return None


def tracker_match(host: str, trackers: TrackerList) -> TrackerMatch | None:
    return _lookup(host, trackers.trackers)


def consent_manager_match(host: str, trackers: TrackerList) -> TrackerMatch | None:
    return _lookup(host, trackers.consent_managers)


def is_third_party(host: str, site_domain: str) -> bool:
    return registrable_domain(host) != site_domain
