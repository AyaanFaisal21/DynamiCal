"""Deterministic tools the chat model can call.

Each tool is plain code over the database. The model picks which to call and
turns the results into an answer. Dates in results are shown in the user's
time zone so the model does not have to convert.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select

from ..calendar.conflicts import find_conflicts
from ..calendar.freetime import free_slots, suggest_blocks
from ..config import Settings
from ..dates import day_bounds, fmt_range, now_utc, parse_date, parse_datetime, to_local
from ..db import Database
from ..ingest.upsert import upsert_event
from ..llm.base import ToolSpec
from ..models import Event, Message, Task


@dataclass
class ToolContext:
    db: Database
    settings: Settings
    now: datetime

    @property
    def today(self) -> date:
        return to_local(self.now, self.settings.tz).date()


def event_brief(e: Event, tz) -> dict[str, Any]:
    out = {
        "id": e.id,
        "title": e.title,
        "when": fmt_range(e.start, e.end, tz, e.all_day),
        "start": to_local(e.start, tz).isoformat(),
        "end": to_local(e.end, tz).isoformat() if e.end else None,
        "all_day": e.all_day,
        "kind": e.kind,
        "status": e.status,
    }
    if e.tentative:
        out["tentative"] = True
    if e.location:
        out["location"] = e.location
    if e.description:
        out["notes"] = e.description[:300]
    if e.relationship_:
        out["why_on_calendar"] = e.relationship_
    return out


def task_brief(t: Task, tz) -> dict[str, Any]:
    return {
        "id": t.id,
        "title": t.title,
        "due": fmt_range(t.due, None, tz) if t.due else None,
        "kind": t.kind,
        "status": t.status,
        "details": (t.details or "")[:200] or None,
        "event_id": t.event_id,
    }


def build_tools(ctx: ToolContext) -> list[ToolSpec]:
    tz = ctx.settings.tz

    def _range(start_text: str, end_text: str | None):
        start_day = parse_date(start_text) or ctx.today
        end_day = parse_date(end_text) if end_text else start_day
        if end_day < start_day:
            end_day = start_day
        start, _ = day_bounds(start_day, tz)
        _, end = day_bounds(end_day, tz)
        return start, end

    def _events(start, end, statuses=("confirmed",)):
        with ctx.db.session() as s:
            rows = s.scalars(
                select(Event)
                .where(Event.start < end, or_(Event.end > start, Event.start >= start))
                .where(Event.status.in_(statuses))
                .order_by(Event.start)
            ).all()
        return rows

    def get_events(start_date: str, end_date: str | None = None, include_proposed: bool = False) -> dict:
        start, end = _range(start_date, end_date)
        statuses = ("confirmed", "proposed") if include_proposed else ("confirmed",)
        rows = _events(start, end, statuses)
        conflicts = [
            {"a": c.a.id, "b": c.b.id, "severity": c.severity, "overlap_minutes": c.overlap_minutes}
            for c in find_conflicts(rows)
        ]
        return {"events": [event_brief(e, tz) for e in rows], "conflicts": conflicts}

    def get_upcoming(days: int = 14, kinds: list[str] | None = None) -> dict:
        start = ctx.now
        end = ctx.now + timedelta(days=max(1, min(days, 120)))
        rows = _events(start, end)
        if kinds:
            wanted = {k.lower() for k in kinds}
            rows = [e for e in rows if e.kind in wanted]
        return {"events": [event_brief(e, tz) for e in rows]}

    def get_free_time(day: str, min_minutes: int = 30) -> dict:
        target = parse_date(day) or ctx.today
        start, end = day_bounds(target, tz)
        rows = _events(start, end)
        not_before = ctx.now if target == ctx.today else None
        slots = free_slots(
            rows,
            target,
            tz,
            day_start_hour=ctx.settings.day_start_hour,
            day_end_hour=ctx.settings.day_end_hour,
            min_minutes=min_minutes,
            not_before=not_before,
        )
        return {
            "date": target.isoformat(),
            "free": [{"when": fmt_range(s.start, s.end, tz), "minutes": s.minutes} for s in slots],
            "total_free_minutes": sum(s.minutes for s in slots),
        }

    def get_tasks(status: str = "open", due_within_days: int | None = None) -> dict:
        with ctx.db.session() as s:
            q = select(Task).where(Task.status == status).order_by(Task.due.is_(None), Task.due)
            rows = s.scalars(q).all()
        if due_within_days is not None:
            limit = ctx.now + timedelta(days=due_within_days)
            rows = [t for t in rows if t.due is None or t.due <= limit]
        return {"tasks": [task_brief(t, tz) for t in rows[:50]]}

    def get_proposals() -> dict:
        with ctx.db.session() as s:
            rows = s.scalars(select(Event).where(Event.status == "proposed").order_by(Event.start)).all()
        return {"proposals": [{**event_brief(e, tz), "reason": e.rationale} for e in rows]}

    def search_events(query: str) -> dict:
        like = f"%{query.strip()}%"
        with ctx.db.session() as s:
            rows = s.scalars(
                select(Event)
                .where(Event.status.in_(("confirmed", "proposed")))
                .where(or_(Event.title.ilike(like), Event.description.ilike(like), Event.location.ilike(like)))
                .order_by(Event.start)
                .limit(25)
            ).all()
        return {"events": [event_brief(e, tz) for e in rows]}

    def get_event_source(event_id: int) -> dict:
        with ctx.db.session() as s:
            e = s.get(Event, event_id)
            if e is None:
                return {"error": "no such event"}
            m = s.get(Message, e.source_message_id) if e.source_message_id else None
            out = {**event_brief(e, tz), "rationale": e.rationale, "confidence": e.confidence}
            if m is not None:
                out["email"] = {
                    "subject": m.subject,
                    "from": f"{m.from_name} <{m.from_email}>".strip(),
                    "sent": fmt_range(m.date, None, tz),
                    "excerpt": m.body_text[:1500],
                }
            return out

    def suggest_study_blocks(event_id: int, total_minutes: int = 180) -> dict:
        with ctx.db.session() as s:
            target = s.get(Event, event_id)
            if target is None:
                return {"error": "no such event"}
            rows = _events(ctx.now, target.start + timedelta(days=1))
        blocks = suggest_blocks(
            rows,
            target_start=target.start,
            total_minutes=max(30, min(total_minutes, 1200)),
            tz=tz,
            day_start_hour=ctx.settings.day_start_hour,
            day_end_hour=ctx.settings.day_end_hour,
            now=ctx.now,
        )
        return {
            "target": event_brief(target, tz),
            "suggestions": [
                {
                    "when": fmt_range(b.start, b.end, tz),
                    "start": to_local(b.start, tz).isoformat(),
                    "end": to_local(b.end, tz).isoformat(),
                    "minutes": b.minutes,
                }
                for b in blocks
            ],
            "note": "These are suggestions only. Call create_block to put one on the calendar.",
        }

    def create_block(
        title: str,
        start: str,
        end: str,
        kind: str = "study",
        tentative: bool = True,
        notes: str | None = None,
    ) -> dict:
        start_dt = parse_datetime(start, tz)
        end_dt = parse_datetime(end, tz)
        if start_dt is None or end_dt is None or end_dt <= start_dt:
            return {"error": "start and end must be ISO 8601 and end must be after start"}
        with ctx.db.session() as s:
            result = upsert_event(
                s,
                title=title,
                start=start_dt,
                end=end_dt,
                tz=tz,
                status="confirmed",
                source="chat",
                kind=kind if kind in ("study", "practice", "event", "other", "meeting", "social") else "study",
                description=notes,
                tentative=tentative,
                relationship="personal",
                confidence=1.0,
                rationale="created from chat",
            )
            created = result.event
            brief = event_brief(created, tz) if created else None
        return {"created": result.action == "created", "event": brief}

    def create_task(title: str, due: str | None = None, kind: str = "todo", details: str | None = None) -> dict:
        due_dt = parse_datetime(due, tz) if due else None
        with ctx.db.session() as s:
            task = Task(title=title.strip(), due=due_dt, kind=kind if kind in ("assignment", "reading", "prep", "todo") else "todo", details=details)
            s.add(task)
            s.flush()
            brief = task_brief(task, tz)
        return {"created": True, "task": brief}

    def complete_task(task_id: int) -> dict:
        with ctx.db.session() as s:
            task = s.get(Task, task_id)
            if task is None:
                return {"error": "no such task"}
            task.status = "done"
            task.updated_at = now_utc()
            return {"done": True, "task": task_brief(task, tz)}

    date_prop = {"type": "string", "description": "YYYY-MM-DD in the user's time zone"}
    datetime_prop = {"type": "string", "description": "ISO 8601 date-time, for example 2026-10-20T18:00:00"}

    return [
        ToolSpec(
            "get_events",
            "Events on the calendar between two dates, inclusive. Also returns time conflicts in that range.",
            {
                "type": "object",
                "properties": {
                    "start_date": date_prop,
                    "end_date": {**date_prop, "description": "YYYY-MM-DD. Defaults to start_date."},
                    "include_proposed": {"type": "boolean", "description": "Include items awaiting the user's review."},
                },
                "required": ["start_date"],
            },
            get_events,
        ),
        ToolSpec(
            "get_upcoming",
            "Confirmed events in the next N days, optionally filtered by kind: exam, deadline, interview, class, meeting, appointment, social, event, study, practice.",
            {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "How far ahead to look. Default 14."},
                    "kinds": {"type": "array", "items": {"type": "string"}},
                },
            },
            get_upcoming,
        ),
        ToolSpec(
            "get_free_time",
            "Free time slots on one day between the user's day start and day end.",
            {
                "type": "object",
                "properties": {"day": date_prop, "min_minutes": {"type": "integer"}},
                "required": ["day"],
            },
            get_free_time,
        ),
        ToolSpec(
            "get_tasks",
            "To-do items: assignments, readings, preparation, and other tasks.",
            {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["open", "done"]},
                    "due_within_days": {"type": "integer"},
                },
            },
            get_tasks,
        ),
        ToolSpec(
            "get_proposals",
            "Events found in email that await the user's accept or reject decision.",
            {"type": "object", "properties": {}},
            get_proposals,
        ),
        ToolSpec(
            "search_events",
            "Find events by a word in the title, notes, or location.",
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            search_events,
        ),
        ToolSpec(
            "get_event_source",
            "Details for one event, including the email it came from. Use this for 'what is this about'.",
            {"type": "object", "properties": {"event_id": {"type": "integer"}}, "required": ["event_id"]},
            get_event_source,
        ),
        ToolSpec(
            "suggest_study_blocks",
            "Suggest study or practice blocks in free time before an exam, deadline, or other event. Does not change the calendar.",
            {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer"},
                    "total_minutes": {"type": "integer", "description": "Total preparation time wanted. Default 180."},
                },
                "required": ["event_id"],
            },
            suggest_study_blocks,
        ),
        ToolSpec(
            "create_block",
            "Put a tentative study, practice, or other block on the calendar. Only call this when the user asks for it.",
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": datetime_prop,
                    "end": datetime_prop,
                    "kind": {"type": "string", "enum": ["study", "practice", "event", "meeting", "social", "other"]},
                    "tentative": {"type": "boolean"},
                    "notes": {"type": "string"},
                },
                "required": ["title", "start", "end"],
            },
            create_block,
        ),
        ToolSpec(
            "create_task",
            "Add a to-do item. Only call this when the user asks for it.",
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "due": datetime_prop,
                    "kind": {"type": "string", "enum": ["assignment", "reading", "prep", "todo"]},
                    "details": {"type": "string"},
                },
                "required": ["title"],
            },
            create_task,
        ),
        ToolSpec(
            "complete_task",
            "Mark a to-do item as done.",
            {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]},
            complete_task,
        ),
    ]
