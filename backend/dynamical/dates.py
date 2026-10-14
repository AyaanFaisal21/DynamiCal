"""Date helpers. Everything stored is UTC and timezone-aware."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from dateutil import parser as dtparser

UTC = timezone.utc


def now_utc() -> datetime:
    return datetime.now(UTC)


def ensure_aware(dt: datetime, tz: ZoneInfo) -> datetime:
    """Give a naive datetime the zone `tz`. Leave aware datetimes alone."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=tz)


def to_utc(dt: datetime, tz: ZoneInfo) -> datetime:
    return ensure_aware(dt, tz).astimezone(UTC)


def to_local(dt: datetime, tz: ZoneInfo) -> datetime:
    return ensure_aware(dt, UTC).astimezone(tz)


def parse_datetime(text: str | None, tz: ZoneInfo) -> datetime | None:
    """Parse an ISO 8601 or free-form timestamp. Returns UTC, or None if unparseable."""
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    # datetime.fromisoformat handles the strict ISO forms, including offsets.
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return to_utc(dt, tz)
    except ValueError:
        pass
    try:
        dt = dtparser.parse(text)
    except (ValueError, OverflowError, TypeError):
        return None
    return to_utc(dt, tz)


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    text = text.strip()
    try:
        return date.fromisoformat(text[:10]) if re.match(r"^\d{4}-\d{2}-\d{2}", text) else dtparser.parse(text).date()
    except (ValueError, OverflowError, TypeError):
        return None


def local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


def day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC start and end of a local calendar day."""
    start = local_midnight(day, tz)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def week_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC bounds of the Monday-to-Sunday week that contains `day`."""
    monday = day - timedelta(days=day.weekday())
    start = local_midnight(monday, tz)
    return start.astimezone(UTC), (start + timedelta(days=7)).astimezone(UTC)


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def fmt_local(dt: datetime, tz: ZoneInfo, all_day: bool = False) -> str:
    local = to_local(dt, tz)
    if all_day:
        return local.strftime("%a %b %d, %Y")
    return local.strftime("%a %b %d, %Y %I:%M %p").replace(" 0", " ")


def fmt_range(start: datetime, end: datetime | None, tz: ZoneInfo, all_day: bool = False) -> str:
    if all_day or end is None:
        return fmt_local(start, tz, all_day)
    s, e = to_local(start, tz), to_local(end, tz)
    if s.date() == e.date():
        return f"{fmt_local(start, tz)} to {e.strftime('%I:%M %p').lstrip('0')}"
    return f"{fmt_local(start, tz)} to {fmt_local(end, tz)}"
