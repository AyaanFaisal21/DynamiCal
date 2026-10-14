"""Daily and weekly digests: what is on, what is due, where the free time is.

Everything here is assembled by code. The optional narrative at the end is
the only model call, and the digest is complete without it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import or_, select

from ..calendar.conflicts import find_conflicts
from ..calendar.freetime import free_slots
from ..config import Settings
from ..dates import day_bounds, fmt_range, now_utc, to_local, week_bounds
from ..db import Database
from ..llm.base import LLMBackend, LLMError
from ..models import Event, Task

HORIZON_DAYS = 14
PREP_KINDS = ("exam", "deadline", "interview")


class Narrative(BaseModel):
    text: str


def build_digest(db: Database, settings: Settings, scope: str, day: date, now: datetime | None = None) -> dict[str, Any]:
    now = now or now_utc()
    tz = settings.tz
    start, end = week_bounds(day, tz) if scope == "week" else day_bounds(day, tz)
    horizon_end = end + timedelta(days=HORIZON_DAYS)

    with db.session() as s:
        in_window = s.scalars(
            select(Event)
            .where(Event.start < end, or_(Event.end > start, Event.start >= start), Event.status == "confirmed")
            .order_by(Event.start)
        ).all()
        proposed = s.scalars(
            select(Event).where(Event.start < end, Event.start >= start, Event.status == "proposed").order_by(Event.start)
        ).all()
        ahead = s.scalars(
            select(Event)
            .where(Event.start >= end, Event.start < horizon_end, Event.status == "confirmed", Event.kind.in_(PREP_KINDS))
            .order_by(Event.start)
        ).all()
        tasks = s.scalars(select(Task).where(Task.status == "open").order_by(Task.due.is_(None), Task.due)).all()
        prep_blocks = s.scalars(
            select(Event).where(Event.kind.in_(("study", "practice")), Event.status == "confirmed", Event.start >= now)
        ).all()

    days: list[dict[str, Any]] = []
    cursor = to_local(start, tz).date()
    last = to_local(end - timedelta(seconds=1), tz).date()
    while cursor <= last:
        d_start, d_end = day_bounds(cursor, tz)
        todays = [e for e in in_window if e.start < d_end and (e.end or e.start) >= d_start]
        slots = free_slots(
            todays,
            cursor,
            tz,
            day_start_hour=settings.day_start_hour,
            day_end_hour=settings.day_end_hour,
            min_minutes=45,
            not_before=now if cursor == to_local(now, tz).date() else None,
        )
        days.append(
            {
                "date": cursor.isoformat(),
                "label": cursor.strftime("%A %b %d"),
                "events": [_event(e, tz) for e in todays],
                "free": [{"when": fmt_range(sl.start, sl.end, tz), "minutes": sl.minutes} for sl in slots],
                "free_minutes": sum(sl.minutes for sl in slots),
            }
        )
        cursor += timedelta(days=1)

    due_in_window = [t for t in tasks if t.due and start <= t.due < end]
    overdue = [t for t in tasks if t.due and t.due < max(start, now)]
    undated = [t for t in tasks if t.due is None][:10]

    coming_up = []
    for e in ahead:
        days_away = (to_local(e.start, tz).date() - to_local(now, tz).date()).days
        planned = sum(
            _minutes(b) for b in prep_blocks if b.start < e.start and _mentions(b, e)
        )
        coming_up.append({**_event(e, tz), "days_away": days_away, "prep_minutes_planned": planned})

    conflicts = [
        {"a": _event(c.a, tz), "b": _event(c.b, tz), "severity": c.severity, "overlap_minutes": c.overlap_minutes}
        for c in find_conflicts(in_window)
    ]

    suggestions = []
    for item in coming_up:
        if item["kind"] in ("exam", "interview") and item["prep_minutes_planned"] == 0:
            suggestions.append(f"No preparation time is planned for {item['title']} in {item['days_away']} day(s).")
    for t in overdue:
        suggestions.append(f"Overdue: {t.title}.")
    if proposed:
        suggestions.append(f"{len(proposed)} proposed event(s) in this period wait for your review.")

    return {
        "scope": scope,
        "start": to_local(start, tz).date().isoformat(),
        "end": to_local(end - timedelta(seconds=1), tz).date().isoformat(),
        "days": days,
        "tasks_due": [_task(t, tz) for t in due_in_window],
        "tasks_overdue": [_task(t, tz) for t in overdue],
        "tasks_undated": [_task(t, tz) for t in undated],
        "coming_up": coming_up,
        "conflicts": conflicts,
        "proposed": [_event(e, tz) for e in proposed],
        "suggestions": suggestions,
        "total_free_minutes": sum(d["free_minutes"] for d in days),
    }


def narrate(digest: dict[str, Any], settings: Settings, backend: LLMBackend) -> str | None:
    """Three to five sentences in the user's context. None when the model fails."""
    compact = {
        k: digest[k]
        for k in ("scope", "start", "end", "tasks_due", "tasks_overdue", "coming_up", "conflicts", "suggestions", "total_free_minutes")
    }
    compact["days"] = [
        {"label": d["label"], "events": [f"{e['when']} {e['title']} ({e['kind']})" for e in d["events"]], "free_minutes": d["free_minutes"]}
        for d in digest["days"]
    ]
    system = (
        "You write a short briefing for one user about their calendar. "
        f"User: {settings.user_profile or 'a student'}. "
        "Three to five sentences, plain text. Name the most important items and say where the free time is. "
        "Do not invent anything that is not in the data."
    )
    try:
        return backend.structured(system=system, prompt=str(compact), schema=Narrative).text.strip()
    except LLMError:
        return None


def _event(e: Event, tz) -> dict[str, Any]:
    return {
        "id": e.id,
        "title": e.title,
        "when": fmt_range(e.start, e.end, tz, e.all_day),
        "start": e.start.isoformat(),
        "end": e.end.isoformat() if e.end else None,
        "kind": e.kind,
        "status": e.status,
        "tentative": e.tentative,
        "location": e.location,
    }


def _task(t: Task, tz) -> dict[str, Any]:
    return {
        "id": t.id,
        "title": t.title,
        "due": fmt_range(t.due, None, tz) if t.due else None,
        "due_iso": t.due.isoformat() if t.due else None,
        "kind": t.kind,
        "details": t.details,
        "event_id": t.event_id,
    }


def _minutes(e: Event) -> int:
    if e.end is None:
        return 60
    return int((e.end - e.start).total_seconds() // 60)


def _mentions(block: Event, target: Event) -> bool:
    words = {w for w in target.title.lower().split() if len(w) > 2}
    text = f"{block.title} {block.description or ''}".lower()
    return any(w in text for w in words)
