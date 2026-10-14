"""ORM tables.

messages   raw emails that were fetched, with the triage result
events     calendar items, including proposed ones and user blocks
tasks      to-do items, often derived from events or emails
chat       the side-panel conversation
sync_state key/value bookkeeping for incremental sync
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .dates import now_utc
from .db import Base, UTCDateTime

EVENT_KINDS = (
    "event",
    "class",
    "exam",
    "deadline",
    "meeting",
    "appointment",
    "social",
    "interview",
    "study",
    "practice",
    "other",
)
EVENT_STATUSES = ("confirmed", "proposed", "rejected", "cancelled")
EVENT_SOURCES = ("email", "ics", "manual", "chat", "gcal")
RELATIONSHIPS = (
    "registered",  # the user signed up, bought a ticket, or booked it
    "personal",  # a real person wrote to the user
    "invited",  # an invitation to the user by name
    "course",  # a class the user is enrolled in
    "informational",  # an org told the user about something, no sign-up on record
    "promotional",  # marketing
    "none",
)
TASK_KINDS = ("assignment", "reading", "prep", "todo")
TASK_STATUSES = ("open", "done")
TRIAGE_DECISIONS = ("skip", "extract", "ics")
MESSAGE_STATUSES = ("new", "skipped", "processed", "error")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    thread_id: Mapped[str | None] = mapped_column(String(128), index=True)
    subject: Mapped[str] = mapped_column(Text, default="")
    from_name: Mapped[str] = mapped_column(String(256), default="")
    from_email: Mapped[str] = mapped_column(String(256), default="", index=True)
    to_header: Mapped[str] = mapped_column(Text, default="")
    date: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    snippet: Mapped[str] = mapped_column(Text, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    labels: Mapped[str] = mapped_column(Text, default="")  # comma separated Gmail labels

    has_ics: Mapped[bool] = mapped_column(Boolean, default=False)
    ics_text: Mapped[str | None] = mapped_column(Text)
    list_unsubscribe: Mapped[bool] = mapped_column(Boolean, default=False)
    list_id: Mapped[str | None] = mapped_column(String(256))

    triage_decision: Mapped[str | None] = mapped_column(String(16))
    triage_score: Mapped[int | None] = mapped_column(Integer)
    triage_reasons: Mapped[str | None] = mapped_column(Text)  # JSON list
    extraction_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    error: Mapped[str | None] = mapped_column(Text)

    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    events: Mapped[list["Event"]] = relationship(back_populates="source_message")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    start: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    end: Mapped[datetime | None] = mapped_column(UTCDateTime)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    tz: Mapped[str] = mapped_column(String(64), default="UTC")

    kind: Mapped[str] = mapped_column(String(32), default="event")
    status: Mapped[str] = mapped_column(String(16), default="confirmed", index=True)
    tentative: Mapped[bool] = mapped_column(Boolean, default=False)

    source: Mapped[str] = mapped_column(String(16), default="manual")
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    thread_id: Mapped[str | None] = mapped_column(String(128), index=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    relationship_: Mapped[str | None] = mapped_column("relationship", String(32))
    rationale: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(256))

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc, onupdate=now_utc)

    source_message: Mapped[Message | None] = relationship(back_populates="events")
    tasks: Mapped[list["Task"]] = relationship(back_populates="event")

    __table_args__ = (Index("ix_events_start_status", "start", "status"),)

    @property
    def is_active(self) -> bool:
        return self.status in ("confirmed", "proposed")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text)
    due: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="todo")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=2)  # 1 high, 2 normal, 3 low
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc, onupdate=now_utc)

    event: Mapped[Event | None] = relationship(back_populates="tasks")


class ChatMessage(Base):
    __tablename__ = "chat"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    tool_log: Mapped[str | None] = mapped_column(Text)  # JSON list of tool calls made
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc, index=True)


class SyncState(Base):
    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc, onupdate=now_utc)
