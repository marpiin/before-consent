"""Download the tracker list and record where it came from."""

import hashlib
import json
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from before_consent import __version__

DISCONNECT_URL = (
    "https://raw.githubusercontent.com/disconnectme/disconnect-tracking-protection/"
    "master/services.json"
)
DISCONNECT_LICENSE = "CC BY-NC-SA 4.0"
LIST_FILE = "disconnect-services.json"
META_FILE = "disconnect-services.meta.json"
MAX_LIST_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class ListSnapshot:
    source_url: str
    license: str
    fetched_at: str
    sha256: str
    size_bytes: int


def fetch_disconnect(lists_dir: Path, timeout: float = 30.0) -> ListSnapshot:
    request = urllib.request.Request(
        DISCONNECT_URL, headers={"User-Agent": f"before-consent/{__version__} (list download)"}
    )
    # The URL is a constant https address, not user input.
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = response.read(MAX_LIST_BYTES + 1)
    if len(body) > MAX_LIST_BYTES:
        raise ValueError(f"tracker list is larger than {MAX_LIST_BYTES} bytes, refusing it")
    # Parse before writing so a broken download never replaces a good list.
    json.loads(body)
    snapshot = ListSnapshot(
        source_url=DISCONNECT_URL,
        license=DISCONNECT_LICENSE,
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
        sha256=hashlib.sha256(body).hexdigest(),
        size_bytes=len(body),
    )
    lists_dir.mkdir(parents=True, exist_ok=True)
    (lists_dir / LIST_FILE).write_bytes(body)
    (lists_dir / META_FILE).write_text(json.dumps(asdict(snapshot), indent=2), encoding="utf-8")
    return snapshot


def read_snapshot(lists_dir: Path) -> ListSnapshot | None:
    meta = lists_dir / META_FILE
    if not meta.exists() or not (lists_dir / LIST_FILE).exists():
        return None
    return ListSnapshot(**json.loads(meta.read_text(encoding="utf-8")))
