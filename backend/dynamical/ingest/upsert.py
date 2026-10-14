"""Insert or update events without creating duplicates.

Three keys identify an existing event, tried in order:
  1. external_id      the UID inside a calendar file
  2. fingerprint      normalised title + local date
  3. thread           same email thread, same day or same title
A rejected event is never resurrected. A confirmed event is never downgraded.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dates import now_utc, to_local
from ..models import Event, Task

_PREFIXES = re.compile(
    r"^\s*(?:(?:re|fwd?|fw|reminder|invitation|updated invitation|accepted|declined|tentative|"
    r"canceled event|cancelled event|canceled|cancelled|confirmed|confirmation)\s*:\s*|\[[^\]]*\]\s*)+",
    re.I,
)
_GCAL_SUFFIX = re.compile(r"\s+@\s+.*$")
_NON_WORD = re.compile(r"[^a-z0-9 ]+")
SPECIFIC_KINDS = ("exam", "deadline", "interview", "appointment", "class", "meeting", "social")


def normalise_title(title: str) -> str:
    t = title.lower().strip()
    t = _PREFIXES.sub("", t)
    t = _GCAL_SUFFIX.sub("", t)
    t = _NON_WORD.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def fingerprint(title: str, start: datetime, tz: ZoneInfo) -> str:
    key = f"{normalise_title(title)}|{to_local(start, tz).date().isoformat()}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


@dataclass
class UpsertResult:
    event: Event | None
    action: str  # created | updated | unchanged | cancelled | skipped


def upsert_event(
    session: Session,
    *,
    title: str,
    start: datetime,
    end: datetime | None,
    tz: ZoneInfo,
    status: str,
    source: str,
    all_day: bool = False,
    kind: str = "event",
    location: str | None = None,
    description: str | None = None,
    source_message_id: str | None = None,
    thread_id: str | None = None,
    relationship: str | None = None,
    confidence: float | None = None,
    rationale: str | None = None,
    external_id: str | None = None,
    tentative: bool = False,
    is_cancellation: bool = False,
    is_update: bool = False,
    exclude_message_id: str | None = None,
) -> UpsertResult:
    fp = fingerprint(title, start, tz)
    existing = find_existing(
        session,
        external_id=external_id,
        fp=fp,
        thread_id=thread_id,
        title=title,
        start=start,
        tz=tz,
        loose=is_update,
        exclude_message_id=exclude_message_id,
    )

    if existing is None:
        if is_cancellation:
            return UpsertResult(None, "skipped")
        event = Event(
            title=title.strip(),
            description=description,
            location=location,
            start=start,
            end=end,
            all_day=all_day,
            tz=tz.key,
            kind=kind,
            status=status,
            tentative=tentative,
            source=source,
            source_message_id=source_message_id,
            thread_id=thread_id,
            fingerprint=fp,
            confidence=confidence,
            relationship_=relationship,
            rationale=rationale,
            external_id=external_id,
        )
        session.add(event)
        session.flush()
        return UpsertResult(event, "created")

    if existing.status == "rejected":
        return UpsertResult(existing, "skipped")

    if is_cancellation:
        existing.status = "cancelled"
        existing.rationale = rationale or existing.rationale
        existing.source_message_id = source_message_id or existing.source_message_id
        session.flush()
        return UpsertResult(existing, "cancelled")

    changed = False

    def set_if(attr: str, value) -> None:
        nonlocal changed
        if value is not None and value != getattr(existing, attr):
            setattr(existing, attr, value)
            changed = True

    if normalise_title(title) != normalise_title(existing.title):
        set_if("title", title.strip())
    set_if("start", start)
    set_if("end", end)
    set_if("all_day", all_day)
    set_if("location", location)
    set_if("description", description)
    if kind in SPECIFIC_KINDS and existing.kind not in SPECIFIC_KINDS:
        set_if("kind", kind)
    set_if("relationship_", relationship)
    if confidence is not None and (existing.confidence is None or confidence > existing.confidence):
        set_if("confidence", confidence)
    set_if("rationale", rationale)
    set_if("external_id", external_id)
    if source_message_id and source_message_id != existing.source_message_id:
        existing.source_message_id = source_message_id
        changed = True
    if thread_id and not existing.thread_id:
        existing.thread_id = thread_id
        changed = True

    # Status only moves up: proposed -> confirmed, cancelled -> back to the new status.
    if existing.status == "cancelled" or (existing.status == "proposed" and status == "confirmed"):
        existing.status = status
        changed = True

    if existing.fingerprint != fp:
        existing.fingerprint = fp
        changed = True

    if changed:
        existing.updated_at = now_utc()
        session.flush()
        return UpsertResult(existing, "updated")
    return UpsertResult(existing, "unchanged")


def find_existing(
    session: Session,
    *,
    external_id: str | None,
    fp: str,
    thread_id: str | None,
    title: str,
    start: datetime,
    tz: ZoneInfo,
    loose: bool = False,
    exclude_message_id: str | None = None,
) -> Event | None:
    """Events extracted from the same email are distinct by construction, so the
    thread rule skips them. `loose` widens title matching when the model said
    the email updates an earlier event."""
    if external_id:
        found = session.scalars(select(Event).where(Event.external_id == external_id)).first()
        if found is not None:
            return found
    found = session.scalars(select(Event).where(Event.fingerprint == fp)).first()
    if found is not None:
        return found
    if thread_id:
        norm = normalise_title(title)
        local_day = to_local(start, tz).date()
        query = select(Event).where(Event.thread_id == thread_id)
        if exclude_message_id:
            query = query.where(
                (Event.source_message_id != exclude_message_id) | (Event.source_message_id.is_(None))
            )
        for candidate in session.scalars(query).all():
            same_day = to_local(candidate.start, tz).date() == local_day
            if same_day or titles_related(normalise_title(candidate.title), norm, loose=loose):
                return candidate
    return None


_STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "in", "on", "at", "and", "with", "moved", "rescheduled",
    "updated", "update", "new", "time", "date", "reminder", "re", "fwd", "is", "now", "this", "next",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "mon", "tue", "wed", "thu", "fri", "sat", "sun",
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "sept", "oct", "nov", "dec",
}


def titles_related(a: str, b: str, *, loose: bool = False) -> bool:
    """Strict: the titles share most of their key words (Jaccard 0.75).
    Loose: the shorter title's key words are nearly all in the longer one."""
    words_a = {w for w in a.split() if w not in _STOPWORDS}
    words_b = {w for w in b.split() if w not in _STOPWORDS}
    if not words_a or not words_b:
        return False
    shared = len(words_a & words_b)
    if loose:
        return shared / min(len(words_a), len(words_b)) >= 0.8
    return shared / len(words_a | words_b) >= 0.75


def upsert_task(
    session: Session,
    *,
    title: str,
    due: datetime | None,
    kind: str = "todo",
    details: str | None = None,
    event_id: int | None = None,
    source_message_id: str | None = None,
    tz: ZoneInfo,
) -> tuple[Task, bool]:
    """Return (task, created). Tasks match on normalised title and local due date."""
    norm = normalise_title(title)
    due_day = to_local(due, tz).date() if due else None
    for candidate in session.scalars(select(Task).where(Task.status == "open")).all():
        cand_day = to_local(candidate.due, tz).date() if candidate.due else None
        if normalise_title(candidate.title) == norm and cand_day == due_day:
            if details and not candidate.details:
                candidate.details = details
            if event_id and not candidate.event_id:
                candidate.event_id = event_id
            return candidate, False
    task = Task(
        title=title.strip(),
        details=details,
        due=due,
        kind=kind,
        event_id=event_id,
        source_message_id=source_message_id,
    )
    session.add(task)
    session.flush()
    return task, True
