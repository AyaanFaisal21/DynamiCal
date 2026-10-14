"""Find events that overlap in time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..models import Event

DEFAULT_DURATION = timedelta(hours=1)
# Deadlines are points in time. They do not occupy the calendar.
POINT_KINDS = ("deadline",)


def effective_end(event: Event) -> datetime:
    if event.end is not None and event.end > event.start:
        return event.end
    if event.kind in POINT_KINDS:
        return event.start
    return event.start + DEFAULT_DURATION


@dataclass
class Conflict:
    a: Event
    b: Event
    severity: str  # hard | soft
    overlap_minutes: int

    @property
    def key(self) -> tuple[int, int]:
        return (min(self.a.id, self.b.id), max(self.a.id, self.b.id))


def find_conflicts(events: list[Event]) -> list[Conflict]:
    """Sweep sorted events once. Soft when one side is tentative or only proposed."""
    active = sorted(
        (
            e
            for e in events
            if e.status in ("confirmed", "proposed") and not e.all_day and e.kind not in POINT_KINDS
        ),
        key=lambda e: e.start,
    )
    out: list[Conflict] = []
    for i, first in enumerate(active):
        first_end = effective_end(first)
        for second in active[i + 1 :]:
            if second.start >= first_end:
                break
            overlap = min(first_end, effective_end(second)) - second.start
            minutes = int(overlap.total_seconds() // 60)
            if minutes <= 0:
                continue
            soft = (
                first.tentative
                or second.tentative
                or first.status == "proposed"
                or second.status == "proposed"
            )
            out.append(Conflict(first, second, "soft" if soft else "hard", minutes))
    return out
