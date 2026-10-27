"""Visit order and the waits between visits."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")


def rotation(sites: Sequence[T], repetitions: int) -> list[tuple[T, int]]:
    """Visit every site once per round, so repeated visits to one site are far apart."""
    return [(site, round_) for round_ in range(1, repetitions + 1) for site in sites]


@dataclass
class Pacer:
    gap_seconds: float
    same_site_gap_seconds: float
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last_end: float | None = None
    _site_last_end: dict[str, float] = field(default_factory=dict)

    def wait_turn(self, site: str) -> float:
        """Sleep until both gaps, measured from the end of earlier visits, have passed."""
        ready = self.clock()
        if self._last_end is not None:
            ready = max(ready, self._last_end + self.gap_seconds)
        if site in self._site_last_end:
            ready = max(ready, self._site_last_end[site] + self.same_site_gap_seconds)
        wait = ready - self.clock()
        if wait > 0:
            self.sleep(wait)
        return max(wait, 0.0)

    def finished(self, site: str) -> None:
        now = self.clock()
        self._last_end = now
        self._site_last_end[site] = now
