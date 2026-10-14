"""Find free time in a day, and place study blocks before a target event."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..dates import UTC, to_local
from ..models import Event
from .conflicts import POINT_KINDS, effective_end


@dataclass
class FreeSlot:
    start: datetime  # UTC
    end: datetime  # UTC

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def busy_intervals(events: list[Event], *, include_tentative: bool = True) -> list[tuple[datetime, datetime]]:
    intervals = []
    for e in events:
        if e.status != "confirmed" or e.all_day or e.kind in POINT_KINDS:
            continue
        if e.tentative and not include_tentative:
            continue
        intervals.append((e.start, effective_end(e)))
    return merge(intervals)


def merge(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def free_slots(
    events: list[Event],
    day: date,
    tz: ZoneInfo,
    *,
    day_start_hour: int,
    day_end_hour: int,
    min_minutes: int = 30,
    include_tentative: bool = True,
    not_before: datetime | None = None,
) -> list[FreeSlot]:
    """Gaps between busy intervals inside the local day window."""
    window_start = datetime.combine(day, time(hour=day_start_hour), tzinfo=tz).astimezone(UTC)
    window_end = datetime.combine(day, time(hour=min(day_end_hour, 23)), tzinfo=tz).astimezone(UTC)
    if day_end_hour >= 24:
        window_end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    if not_before is not None and not_before > window_start:
        window_start = not_before
    if window_start >= window_end:
        return []

    cursor = window_start
    slots: list[FreeSlot] = []
    for start, end in busy_intervals(events, include_tentative=include_tentative):
        if end <= cursor or start >= window_end:
            continue
        if start > cursor:
            slots.append(FreeSlot(cursor, min(start, window_end)))
        cursor = max(cursor, end)
    if cursor < window_end:
        slots.append(FreeSlot(cursor, window_end))
    return [s for s in slots if s.minutes >= min_minutes]


@dataclass
class BlockSuggestion:
    start: datetime
    end: datetime
    day: date

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def suggest_blocks(
    events: list[Event],
    *,
    target_start: datetime,
    total_minutes: int,
    tz: ZoneInfo,
    day_start_hour: int,
    day_end_hour: int,
    now: datetime,
    block_minutes: int = 90,
    max_per_day: int = 1,
) -> list[BlockSuggestion]:
    """Greedy: one block per day, latest days first, inside free slots, until the total is met.

    Working backwards from the target spreads preparation over the days just before it,
    which is when a student actually studies.
    """
    remaining = total_minutes
    out: list[BlockSuggestion] = []
    target_local_day = to_local(target_start, tz).date()
    day = target_local_day
    first_day = to_local(now, tz).date()
    while remaining > 0 and day >= first_day:
        not_before = now if day == first_day else None
        slots = free_slots(
            events,
            day,
            tz,
            day_start_hour=day_start_hour,
            day_end_hour=day_end_hour,
            min_minutes=45,
            not_before=not_before,
        )
        if day == target_local_day:
            slots = [FreeSlot(s.start, min(s.end, target_start)) for s in slots if s.start < target_start]
            slots = [s for s in slots if s.minutes >= 45]
        placed = 0
        for slot in sorted(slots, key=lambda s: s.minutes, reverse=True):
            if placed >= max_per_day or remaining <= 0:
                break
            length = min(block_minutes, slot.minutes, remaining)
            out.append(BlockSuggestion(slot.start, slot.start + timedelta(minutes=length), day))
            remaining -= length
            placed += 1
        day -= timedelta(days=1)
    return sorted(out, key=lambda b: b.start)
