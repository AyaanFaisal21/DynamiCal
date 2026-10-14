"""Read calendar attachments. An .ics file is the one case that needs no model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from icalendar import Calendar

from ..dates import UTC, to_utc


@dataclass
class IcsEvent:
    uid: str | None
    summary: str
    start: datetime  # UTC
    end: datetime | None  # UTC
    all_day: bool
    location: str | None
    description: str | None
    status: str | None  # CONFIRMED | TENTATIVE | CANCELLED
    method: str | None  # REQUEST | CANCEL | PUBLISH | REPLY
    organizer: str | None
    attendees: list[str] = field(default_factory=list)
    tz_name: str | None = None

    @property
    def cancelled(self) -> bool:
        return (self.status or "").upper() == "CANCELLED" or (self.method or "").upper() == "CANCEL"


def parse_ics(text: str, default_tz: ZoneInfo) -> list[IcsEvent]:
    try:
        cal = Calendar.from_ical(text)
    except Exception:
        return []

    method = _as_str(cal.get("METHOD"))
    out: list[IcsEvent] = []
    for comp in cal.walk("VEVENT"):
        try:
            ev = _vevent(comp, method, default_tz)
        except Exception:
            continue
        if ev is not None:
            out.append(ev)
    return out


def _vevent(comp, method: str | None, default_tz: ZoneInfo) -> IcsEvent | None:
    dtstart = comp.get("DTSTART")
    if dtstart is None:
        return None
    start_raw = dtstart.dt
    dtend = comp.get("DTEND")
    end_raw = dtend.dt if dtend is not None else None
    duration = comp.get("DURATION")

    all_day = isinstance(start_raw, date) and not isinstance(start_raw, datetime)
    tz_name: str | None = None

    if all_day:
        start = datetime.combine(start_raw, time.min, tzinfo=default_tz).astimezone(UTC)
        if isinstance(end_raw, date) and not isinstance(end_raw, datetime):
            end = datetime.combine(end_raw, time.min, tzinfo=default_tz).astimezone(UTC)
        else:
            end = start + timedelta(days=1)
        tz_name = default_tz.key
    else:
        tz_name = _tz_name(start_raw) or default_tz.key
        start = to_utc(start_raw, default_tz)
        if isinstance(end_raw, datetime):
            end = to_utc(end_raw, default_tz)
        elif duration is not None and isinstance(duration.dt, timedelta):
            end = start + duration.dt
        else:
            end = start + timedelta(hours=1)

    attendees_raw = comp.get("ATTENDEE")
    if attendees_raw is None:
        attendees: list[str] = []
    elif isinstance(attendees_raw, list):
        attendees = [_mailto(a) for a in attendees_raw]
    else:
        attendees = [_mailto(attendees_raw)]

    return IcsEvent(
        uid=_as_str(comp.get("UID")),
        summary=_as_str(comp.get("SUMMARY")) or "(no title)",
        start=start,
        end=end,
        all_day=all_day,
        location=_as_str(comp.get("LOCATION")) or None,
        description=_as_str(comp.get("DESCRIPTION")) or None,
        status=_as_str(comp.get("STATUS")) or None,
        method=method or None,
        organizer=_mailto(comp.get("ORGANIZER")) or None,
        attendees=[a for a in attendees if a],
        tz_name=tz_name,
    )


def _as_str(value) -> str | None:
    if value is None:
        return None
    try:
        return str(value).strip()
    except Exception:
        return None


def _mailto(value) -> str:
    s = _as_str(value) or ""
    return s[7:].lower() if s.lower().startswith("mailto:") else s.lower()


def _tz_name(dt: datetime) -> str | None:
    tzinfo = dt.tzinfo
    if tzinfo is None:
        return None
    key = getattr(tzinfo, "key", None)
    if key:
        return str(key)
    name = tzinfo.tzname(dt)
    return name if name and name != "UTC" else "UTC"
