"""Settings file loading and the checks that keep the tool polite."""

import hashlib
import json
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from before_consent import __version__

BROWSER_CHANNELS = ("chromium", "chrome", "msedge")
MIN_GAP_SECONDS = 5.0
MIN_SAME_SITE_GAP_SECONDS = 30.0
MAX_VISIT_SECONDS = 45.0


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    contact: str = ""
    settle_seconds: float = 8.0
    repetitions: int = 3
    gap_seconds: float = MIN_GAP_SECONDS
    same_site_gap_seconds: float = MIN_SAME_SITE_GAP_SECONDS
    visit_timeout_seconds: float = MAX_VISIT_SECONDS
    browser_channel: str = "chromium"
    locale: str = "es-ES"
    timezone: str = "Europe/Madrid"
    viewport_width: int = 1366
    viewport_height: int = 768
    show_site_names: bool = False
    min_sites_per_category: int = 5
    database: str = "data/before-consent.sqlite"
    lists_dir: str = "data/lists"
    targets: str = "targets.csv"
    report_dir: str = "report"


def load_settings(path: Path) -> Settings:
    if not path.exists():
        raise ConfigError(f"settings file {path} not found")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(Settings)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"unknown settings in {path}: {', '.join(unknown)}")
    settings = Settings(**raw)
    check_politeness(settings)
    return settings


def check_politeness(settings: Settings) -> None:
    if settings.gap_seconds < MIN_GAP_SECONDS:
        raise ConfigError(f"gap_seconds must be at least {MIN_GAP_SECONDS}")
    if settings.same_site_gap_seconds < MIN_SAME_SITE_GAP_SECONDS:
        raise ConfigError(f"same_site_gap_seconds must be at least {MIN_SAME_SITE_GAP_SECONDS}")
    if not 0 < settings.visit_timeout_seconds <= MAX_VISIT_SECONDS:
        raise ConfigError(f"visit_timeout_seconds must be between 0 and {MAX_VISIT_SECONDS}")
    if not 0 <= settings.settle_seconds < settings.visit_timeout_seconds - 5:
        raise ConfigError("settle_seconds must leave at least 5 s of the visit timeout for loading")
    if settings.repetitions < 1:
        raise ConfigError("repetitions must be at least 1")
    if settings.browser_channel not in BROWSER_CHANNELS:
        raise ConfigError(f"browser_channel must be one of {', '.join(BROWSER_CHANNELS)}")


def require_contact(settings: Settings) -> str:
    contact = settings.contact.strip()
    if not contact:
        raise ConfigError(
            "contact is empty. Set contact in the settings file to a project URL or an address "
            "where site owners can reach you; it is sent in the User-Agent of every request."
        )
    if "example." in contact.lower() or contact.lower().endswith(".example"):
        raise ConfigError("contact looks like a placeholder; use a real project URL or address")
    if " " in contact or not (contact.startswith(("https://", "http://")) or "@" in contact):
        raise ConfigError("contact must be a URL (https://...) or an email address")
    return contact


def user_agent_suffix(contact: str) -> str:
    return f"before-consent-audit/{__version__} (+{contact})"


def settings_sha256(settings: Settings) -> str:
    canonical = json.dumps(asdict(settings), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
