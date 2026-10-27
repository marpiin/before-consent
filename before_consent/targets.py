"""The list of sites to visit."""

import csv
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Target:
    url: str
    category: str


def load_targets(path: Path) -> list[Target]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"url", "category"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing columns: {', '.join(sorted(missing))}")
        targets: list[Target] = []
        seen: set[str] = set()
        for line, row in enumerate(reader, start=2):
            url, category = row["url"].strip(), row["category"].strip()
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise ValueError(f"{path}:{line}: {url!r} is not an http or https URL")
            if parts.path not in ("", "/") or parts.query:
                raise ValueError(f"{path}:{line}: only home pages are visited, got {url!r}")
            if not category:
                raise ValueError(f"{path}:{line}: category is empty")
            if url in seen:
                raise ValueError(f"{path}:{line}: {url} is listed twice")
            seen.add(url)
            targets.append(Target(url, category))
    return targets
