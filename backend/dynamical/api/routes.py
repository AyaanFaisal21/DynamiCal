"""HTTP routes. Thin: validate, call the module that does the work, shape the reply."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload
from starlette.concurrency import run_in_threadpool

from ..calendar.conflicts import find_conflicts
from ..calendar.freetime import free_slots
from ..chat.agent import answer as chat_answer
from ..config import Settings
from ..dates import day_bounds, ensure_aware, fmt_range, local_midnight, now_utc, to_local
from ..gmail.auth import GmailAuthError
from ..ingest.pipeline import Pipeline
from ..ingest.upsert import fingerprint
from ..models import ChatMessage, Event, Message, Task
from ..status import collect_status
from ..todo.digest import build_digest, narrate
from .deps import get_backend_dep, get_db, get_session, get_settings_dep
from .schemas import (
    AlertOut,
    ChatMessageOut,
    ChatRequest,
    ConflictOut,
    EventCreate,
    EventOut,
    EventUpdate,
    FreeSlotOut,
    MessageOut,
    SyncRequest,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)

router = APIRouter()


# -- helpers ---------------------------------------------------------------------------


def _events_between(s: Session, start: datetime, end: datetime, statuses: tuple[str, ...]) -> list[Event]:
    return s.scalars(
        select(Event)
        .options(joinedload(Event.source_message))
        .where(Event.start < end, or_(Event.end > start, Event.start >= start), Event.status.in_(statuses))
        .order_by(Event.start)
    ).all()


def _serialize(rows: list[Event]) -> list[EventOut]:
    conflict_map: dict[int, list[int]] = {}
    for c in find_conflicts(rows):
        conflict_map.setdefault(c.a.id, []).append(c.b.id)
        conflict_map.setdefault(c.b.id, []).append(c.a.id)
    out = []
    for e in rows:
        item = EventOut.model_validate(e)
        item.conflicts = conflict_map.get(e.id, [])
        if e.source_message is not None:
            item.source_subject = e.source_message.subject
            item.source_from = e.source_message.from_name or e.source_message.from_email
        out.append(item)
    return out


def _one(s: Session, event_id: int) -> Event:
    event = s.get(Event, event_id, options=[joinedload(Event.source_message)])
    if event is None:
        raise HTTPException(404, "event not found")
    return event


def _serialize_one(s: Session, event: Event) -> EventOut:
    """Serialize one event with conflicts computed against its neighbours."""
    end = event.end if event.end and event.end > event.start else event.start + timedelta(hours=1)
    neighbours = _events_between(s, event.start, end, ("confirmed", "proposed"))
    rows = neighbours if any(e.id == event.id for e in neighbours) else [*neighbours, event]
    return next(out for out in _serialize(rows) if out.id == event.id)


def _parse_statuses(value: str) -> tuple[str, ...]:
    allowed = {"confirmed", "proposed", "rejected", "cancelled"}
    chosen = tuple(v.strip() for v in value.split(",") if v.strip() in allowed)
    return chosen or ("confirmed", "proposed")


def _range(from_: datetime | None, to: datetime | None, settings: Settings) -> tuple[datetime, datetime]:
    tz = settings.tz
    today = to_local(now_utc(), tz).date()
    start = ensure_aware(from_, tz) if from_ else day_bounds(today - timedelta(days=7), tz)[0]
    end = ensure_aware(to, tz) if to else day_bounds(today + timedelta(days=35), tz)[1]
    if end <= start:
        raise HTTPException(422, "'to' must be after 'from'")
    return start, end


# -- status ------------------------------------------------------------------------------


@router.get("/status")
def status(db=Depends(get_db), settings: Settings = Depends(get_settings_dep), backend=Depends(get_backend_dep)):
    return collect_status(db, settings, backend)


# -- events ------------------------------------------------------------------------------


@router.get("/events", response_model=list[EventOut])
def list_events(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    status: str = "confirmed,proposed",
    s: Session = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
):
    start, end = _range(from_, to, settings)
    return _serialize(_events_between(s, start, end, _parse_statuses(status)))


@router.post("/events", response_model=EventOut, status_code=201)
def create_event(body: EventCreate, s: Session = Depends(get_session), settings: Settings = Depends(get_settings_dep)):
    tz = settings.tz
    start = ensure_aware(body.start, tz)
    end = ensure_aware(body.end, tz) if body.end else None
    if body.all_day:
        start = local_midnight(to_local(start, tz).date(), tz)
        end = local_midnight(to_local(end, tz).date(), tz) if end and end > start else start + timedelta(days=1)
    elif end is None:
        end = start + timedelta(hours=1)
    elif end <= start:
        raise HTTPException(422, "end must be after start")
    event = Event(
        title=body.title.strip(),
        description=body.description,
        location=body.location,
        start=start,
        end=end,
        all_day=body.all_day,
        tz=tz.key,
        kind=body.kind,
        status=body.status,
        tentative=body.tentative,
        source="manual",
        fingerprint=fingerprint(body.title, start, tz),
        relationship_="personal",
        confidence=1.0,
        rationale="created by the user",
    )
    s.add(event)
    s.flush()
    return _serialize_one(s, event)


@router.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: int, s: Session = Depends(get_session)):
    return _serialize_one(s, _one(s, event_id))


@router.get("/events/{event_id}/suggest")
def suggest_for_event(
    event_id: int,
    minutes: int = Query(default=180, ge=30, le=1200),
    s: Session = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
):
    """Free-time study blocks before this event. Suggestions only, nothing is saved."""
    from ..calendar.freetime import suggest_blocks

    target = _one(s, event_id)
    now = now_utc()
    rows = _events_between(s, now, target.start + timedelta(days=1), ("confirmed",))
    blocks = suggest_blocks(
        rows,
        target_start=target.start,
        total_minutes=minutes,
        tz=settings.tz,
        day_start_hour=settings.day_start_hour,
        day_end_hour=settings.day_end_hour,
        now=now,
    )
    return {
        "event_id": target.id,
        "suggestions": [
            {"start": b.start, "end": b.end, "minutes": b.minutes, "when": fmt_range(b.start, b.end, settings.tz)}
            for b in blocks
        ],
    }


@router.patch("/events/{event_id}", response_model=EventOut)
def update_event(event_id: int, body: EventUpdate, s: Session = Depends(get_session), settings: Settings = Depends(get_settings_dep)):
    event = _one(s, event_id)
    tz = settings.tz
    data = body.model_dump(exclude_unset=True)
    if "start" in data and data["start"] is not None:
        data["start"] = ensure_aware(data["start"], tz)
    if "end" in data and data["end"] is not None:
        data["end"] = ensure_aware(data["end"], tz)
    for key, value in data.items():
        setattr(event, key, value)
    if event.end is not None and event.end <= event.start:
        raise HTTPException(422, "end must be after start")
    event.fingerprint = fingerprint(event.title, event.start, tz)
    event.updated_at = now_utc()
    s.flush()
    return _serialize_one(s, event)


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, s: Session = Depends(get_session)):
    event = _one(s, event_id)
    if event.source in ("manual", "chat"):
        s.delete(event)
    else:
        # Keep the row so the same email cannot add it again.
        event.status = "rejected"
        event.updated_at = now_utc()
    return Response(status_code=204)


# -- proposals ----------------------------------------------------------------------------


@router.get("/proposals", response_model=list[EventOut])
def list_proposals(s: Session = Depends(get_session)):
    rows = s.scalars(
        select(Event).options(joinedload(Event.source_message)).where(Event.status == "proposed").order_by(Event.start)
    ).all()
    return _serialize(rows)


@router.post("/proposals/{event_id}/accept", response_model=EventOut)
def accept_proposal(event_id: int, s: Session = Depends(get_session)):
    event = _one(s, event_id)
    event.status = "confirmed"
    event.updated_at = now_utc()
    s.flush()
    return _serialize_one(s, event)


@router.post("/proposals/{event_id}/reject", response_model=EventOut)
def reject_proposal(event_id: int, s: Session = Depends(get_session)):
    event = _one(s, event_id)
    event.status = "rejected"
    event.updated_at = now_utc()
    return _serialize([event])[0]


# -- conflicts, free time, digest, alerts -----------------------------------------------


@router.get("/conflicts", response_model=list[ConflictOut])
def list_conflicts(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    s: Session = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
):
    start, end = _range(from_, to, settings)
    rows = _events_between(s, start, end, ("confirmed", "proposed"))
    by_id = {e.id: out for e, out in zip(rows, _serialize(rows))}
    return [
        ConflictOut(a=by_id[c.a.id], b=by_id[c.b.id], severity=c.severity, overlap_minutes=c.overlap_minutes)
        for c in find_conflicts(rows)
    ]


@router.get("/free", response_model=list[FreeSlotOut])
def free_time(
    day: date | None = Query(default=None, alias="date"),
    min_minutes: int = Query(default=30, ge=5, le=600),
    s: Session = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
):
    tz = settings.tz
    now = now_utc()
    target = day or to_local(now, tz).date()
    start, end = day_bounds(target, tz)
    rows = _events_between(s, start, end, ("confirmed",))
    slots = free_slots(
        rows,
        target,
        tz,
        day_start_hour=settings.day_start_hour,
        day_end_hour=settings.day_end_hour,
        min_minutes=min_minutes,
        not_before=now if target == to_local(now, tz).date() else None,
    )
    return [FreeSlotOut(start=sl.start, end=sl.end, minutes=sl.minutes) for sl in slots]


@router.get("/digest")
async def digest(
    scope: str = Query(default="day", pattern="^(day|week)$"),
    day: date | None = Query(default=None, alias="date"),
    narrative: bool = False,
    db=Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    backend=Depends(get_backend_dep),
):
    target = day or to_local(now_utc(), settings.tz).date()
    result = await run_in_threadpool(build_digest, db, settings, scope, target)
    result["narrative"] = None
    if narrative and backend is not None:
        result["narrative"] = await run_in_threadpool(narrate, result, settings, backend)
    return result


@router.get("/alerts", response_model=list[AlertOut])
def alerts(s: Session = Depends(get_session), settings: Settings = Depends(get_settings_dep)):
    tz = settings.tz
    now = now_utc()
    soon = now + timedelta(hours=48)
    horizon = now + timedelta(days=14)
    out: list[AlertOut] = []

    rows = _events_between(s, now, horizon, ("confirmed", "proposed"))
    for c in find_conflicts(rows):
        if c.severity == "hard":
            out.append(
                AlertOut(
                    severity="high",
                    kind="conflict",
                    message=f"{c.a.title} overlaps {c.b.title} on {to_local(c.a.start, tz).strftime('%a %b %d')}",
                    event_id=c.a.id,
                )
            )
    for e in rows:
        if e.status == "confirmed" and e.kind in ("exam", "deadline", "interview") and e.start <= soon:
            out.append(AlertOut(severity="high", kind="due_soon", message=f"{e.title}: {fmt_range(e.start, None, tz)}", event_id=e.id))

    prep = [e for e in rows if e.kind in ("study", "practice") and e.status == "confirmed"]
    for e in rows:
        if e.status == "confirmed" and e.kind in ("exam", "interview") and e.start > soon:
            words = {w for w in e.title.lower().split() if len(w) > 2}
            planned = any(any(w in (p.title + " " + (p.description or "")).lower() for w in words) for p in prep)
            if not planned:
                days_away = (to_local(e.start, tz).date() - to_local(now, tz).date()).days
                out.append(AlertOut(severity="low", kind="no_prep", message=f"No study time planned for {e.title} (in {days_away} days)", event_id=e.id))

    proposed = s.scalar(select(Event.id).where(Event.status == "proposed").limit(1))
    if proposed is not None:
        count = len(s.scalars(select(Event.id).where(Event.status == "proposed")).all())
        out.append(AlertOut(severity="medium", kind="review", message=f"{count} proposed event(s) wait for your review", count=count))

    errors = len(s.scalars(select(Message.id).where(Message.status == "error")).all())
    if errors:
        out.append(AlertOut(severity="low", kind="errors", message=f"{errors} email(s) failed to process", count=errors))
    waiting = len(s.scalars(select(Message.id).where(Message.status == "new", Message.triage_decision == "extract")).all())
    if waiting:
        out.append(AlertOut(severity="low", kind="waiting", message=f"{waiting} email(s) wait for a model", count=waiting))

    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda a: order[a.severity])


# -- tasks -----------------------------------------------------------------------------------


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(status: str = "open", s: Session = Depends(get_session)):
    q = select(Task).order_by(Task.due.is_(None), Task.due, Task.priority)
    if status in ("open", "done"):
        q = q.where(Task.status == status)
    return s.scalars(q).all()


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, s: Session = Depends(get_session), settings: Settings = Depends(get_settings_dep)):
    task = Task(
        title=body.title.strip(),
        details=body.details,
        due=ensure_aware(body.due, settings.tz) if body.due else None,
        kind=body.kind,
        priority=body.priority,
        event_id=body.event_id,
    )
    s.add(task)
    s.flush()
    return task


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdate, s: Session = Depends(get_session), settings: Settings = Depends(get_settings_dep)):
    task = s.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    data = body.model_dump(exclude_unset=True)
    if data.get("due") is not None:
        data["due"] = ensure_aware(data["due"], settings.tz)
    for key, value in data.items():
        setattr(task, key, value)
    task.updated_at = now_utc()
    s.flush()
    return task


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, s: Session = Depends(get_session)):
    task = s.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    s.delete(task)
    return Response(status_code=204)


# -- messages ---------------------------------------------------------------------------------


def _message_out(m: Message) -> MessageOut:
    extraction = None
    if m.extraction_json:
        try:
            extraction = json.loads(m.extraction_json)
        except json.JSONDecodeError:
            extraction = None
    return MessageOut(
        id=m.id,
        thread_id=m.thread_id,
        subject=m.subject,
        from_name=m.from_name,
        from_email=m.from_email,
        date=m.date,
        snippet=m.snippet,
        labels=[l for l in m.labels.split(",") if l],
        has_ics=m.has_ics,
        triage_decision=m.triage_decision,
        triage_score=m.triage_score,
        triage_reasons=json.loads(m.triage_reasons) if m.triage_reasons else [],
        status=m.status,
        error=m.error,
        extraction=extraction,
        body_excerpt=m.body_text[:2000],
        event_ids=[e.id for e in m.events],
    )


@router.get("/messages", response_model=list[MessageOut])
def list_messages(status: str | None = None, limit: int = Query(default=50, ge=1, le=500), s: Session = Depends(get_session)):
    q = select(Message).options(joinedload(Message.events)).order_by(Message.date.desc()).limit(limit)
    if status:
        q = q.where(Message.status == status)
    return [_message_out(m) for m in s.scalars(q).unique().all()]


@router.get("/messages/{message_id}", response_model=MessageOut)
def get_message(message_id: str, s: Session = Depends(get_session)):
    m = s.get(Message, message_id, options=[joinedload(Message.events)])
    if m is None:
        raise HTTPException(404, "message not found")
    return _message_out(m)


# -- chat --------------------------------------------------------------------------------------


def _chat_out(row: ChatMessage) -> ChatMessageOut:
    calls = None
    if row.tool_log:
        try:
            calls = json.loads(row.tool_log)
        except json.JSONDecodeError:
            calls = None
    return ChatMessageOut(id=row.id, role=row.role, content=row.content, tool_calls=calls, created_at=row.created_at)


@router.get("/chat", response_model=list[ChatMessageOut])
def chat_history(limit: int = Query(default=50, ge=1, le=500), s: Session = Depends(get_session)):
    rows = s.scalars(select(ChatMessage).order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(limit)).all()
    return [_chat_out(r) for r in reversed(rows)]


@router.post("/chat", response_model=ChatMessageOut)
async def chat(body: ChatRequest, db=Depends(get_db), settings: Settings = Depends(get_settings_dep), backend=Depends(get_backend_dep)):
    reply, _ = await run_in_threadpool(chat_answer, db, settings, backend, body.message.strip())
    return _chat_out(reply)


@router.delete("/chat", status_code=204)
def clear_chat(s: Session = Depends(get_session)):
    for row in s.scalars(select(ChatMessage)).all():
        s.delete(row)
    return Response(status_code=204)


# -- sync ----------------------------------------------------------------------------------------


@router.post("/sync")
async def sync(body: SyncRequest | None = None, db=Depends(get_db), settings: Settings = Depends(get_settings_dep), backend=Depends(get_backend_dep)):
    from ..gmail.sync import sync_gmail

    body = body or SyncRequest()
    try:
        report = await run_in_threadpool(
            sync_gmail, db, settings, backend, days=body.days, max_messages=body.max_messages, full=body.full, log=lambda *_: None
        )
    except GmailAuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # surface Gmail API errors to the UI instead of a bare 500
        raise HTTPException(502, f"sync failed: {exc}") from exc
    return {"report": report.as_dict(), "summary": report.summary()}


@router.post("/ingest/pending")
async def ingest_pending(db=Depends(get_db), settings: Settings = Depends(get_settings_dep), backend=Depends(get_backend_dep)):
    report = await run_in_threadpool(Pipeline(db, settings, backend).process_pending)
    return {"report": report.as_dict(), "summary": report.summary()}
