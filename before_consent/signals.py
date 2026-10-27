"""Consent signals, documented tracker cookie names and CMP detection.

Only what has a source in docs/method.md is interpreted. Everything else stays unknown.
"""

import re
from dataclasses import dataclass

# gcs=G1xy: x is ad_storage, y is analytics_storage; 1 granted, 0 denied, - not set.
_GCS = re.compile(r"^G1([01-])([01-])$")
_GCS_STATE = {"1": "granted", "0": "denied", "-": "not_set"}


@dataclass(frozen=True)
class ConsentSignal:
    text: str
    denied: bool


def google_consent_signal(params: dict[str, list[str]]) -> ConsentSignal | None:
    values = params.get("gcs")
    if not values:
        return None
    match = _GCS.match(values[0])
    if not match:
        return ConsentSignal("gcs=unrecognized", denied=False)
    ad, analytics = (_GCS_STATE[c] for c in match.groups())
    return ConsentSignal(
        f"gcs ad_storage={ad} analytics_storage={analytics}",
        denied=ad == "denied" and analytics == "denied",
    )


# First-party cookies set by tracker scripts, named in the vendors' own documentation.
KNOWN_COOKIES = {
    "_ga": "Google",
    "_gcl_au": "Google",
    "_gcl_aw": "Google",
    "_gcl_dc": "Google",
    "_fbp": "Meta",
    "_fbc": "Meta",
}
KNOWN_COOKIE_PREFIXES = {"_ga_": "Google"}


def known_cookie_owner(name: str) -> str | None:
    if name in KNOWN_COOKIES:
        return KNOWN_COOKIES[name]
    for prefix, owner in KNOWN_COOKIE_PREFIXES.items():
        if name.startswith(prefix):
            return owner
    return None


# Globals that the TCF v2 CMP API and three CMP vendors document as their public API.
CMP_PROBE = """() => {
  const found = [];
  if (typeof window.__tcfapi === 'function') found.push('tcf');
  if (typeof window.Cookiebot === 'object' && window.Cookiebot) found.push('cookiebot');
  if (typeof window.Didomi === 'object' && window.Didomi) found.push('didomi');
  if (typeof window.OneTrust === 'object' && window.OneTrust) found.push('onetrust');
  return found;
}"""
