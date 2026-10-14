"""Request and response shapes for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["confirmed", "proposed", "rejected", "cancelled"]


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    title: str
    description: str | None = None
    location: str | None = None
    start: datetime
    end: datetime | None = None
    all_day: bool
    tz: str
    kind: str
    status: str
    tentative: bool
    source: str
    source_message_id: str | None = None
    thread_id: str | None = None
    confidence: float | None = None
    relationship: str | None = Field(default=None, validation_alias="relationship_")
    rationale: str | None = None
    created_at: datetime
    updated_at: datetime
    conflicts: list[int] = Field(default_factory=list)
    source_subject: str | None = None
    source_from: str | None = None


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    start: datetime
    end: datetime | None = None
    all_day: bool = False
    kind: str = "study"
    tentative: bool = True
    location: str | None = None
    description: str | None = None
    status: Literal["confirmed", "proposed"] = "confirmed"


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool | None = None
    kind: str | None = None
    tentative: bool | None = None
    location: str | None = None
    description: str | None = None
    status: Status | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    details: str | None = None
    due: datetime | None = None
    kind: str
    status: str
    priority: int
    event_id: int | None = None
    source_message_id: str | None = None
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    details: str | None = None
    due: datetime | None = None
    kind: str = "todo"
    priority: int = 2
    event_id: int | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    details: str | None = None
    due: datetime | None = None
    kind: str | None = None
    priority: int | None = None
    status: Literal["open", "done"] | None = None
    event_id: int | None = None


class MessageOut(BaseModel):
    id: str
    thread_id: str | None
    subject: str
    from_name: str
    from_email: str
    date: datetime
    snippet: str
    labels: list[str]
    has_ics: bool
    triage_decision: str | None
    triage_score: int | None
    triage_reasons: list[str]
    status: str
    error: str | None
    extraction: dict[str, Any] | None
    body_excerpt: str
    event_ids: list[int]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    created_at: datetime


class SyncRequest(BaseModel):
    days: int | None = Field(default=None, ge=1, le=365)
    max_messages: int | None = Field(default=None, ge=1, le=2000)
    full: bool = False


class ConflictOut(BaseModel):
    a: EventOut
    b: EventOut
    severity: str
    overlap_minutes: int


class FreeSlotOut(BaseModel):
    start: datetime
    end: datetime
    minutes: int


class AlertOut(BaseModel):
    severity: Literal["high", "medium", "low"]
    kind: str
    message: str
    event_id: int | None = None
    count: int | None = None
