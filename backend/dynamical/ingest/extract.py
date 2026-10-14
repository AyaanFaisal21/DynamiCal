"""Ask the model what one email means for the user's calendar.

The model sees the email plus the hints from triage, and returns a strict
JSON object. Everything after this point is ordinary code.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..config import Settings
from ..dates import fmt_local
from ..gmail.parse import ParsedEmail
from ..llm.base import LLMBackend
from .triage import Triage

BODY_FOR_MODEL = 12_000

Relationship = Literal[
    "registered", "personal", "invited", "course", "informational", "promotional", "none"
]
Kind = Literal[
    "event", "class", "exam", "deadline", "meeting", "appointment", "social", "interview", "other"
]


class ExtractedEvent(BaseModel):
    title: str = Field(description="Short, specific title. No marketing words.")
    start: str = Field(
        description="ISO 8601 with offset, for example 2026-10-23T18:00:00-04:00. All-day items use YYYY-MM-DD."
    )
    end: str | None = Field(default=None, description="ISO 8601 end, or null when the email does not say.")
    all_day: bool = False
    location: str | None = None
    kind: Kind = "event"
    description: str | None = Field(
        default=None, description="One or two sentences: what it is and why it matters to the user."
    )
    confidence: float = Field(
        ge=0, le=1, description="Probability that this is a real, specific commitment for the user's calendar."
    )
    is_update: bool = Field(default=False, description="True when this email changes an event the user already had.")
    is_cancellation: bool = False


class ExtractedTask(BaseModel):
    title: str
    due: str | None = Field(default=None, description="ISO 8601 or YYYY-MM-DD, or null.")
    kind: Literal["assignment", "reading", "prep", "todo"] = "todo"
    details: str | None = None


class Extraction(BaseModel):
    relationship: Relationship
    summary: str = Field(description="One sentence: what this email is about.")
    rationale: str = Field(description="One sentence: why this relationship label.")
    events: list[ExtractedEvent] = Field(default_factory=list)
    tasks: list[ExtractedTask] = Field(default_factory=list)


SYSTEM_PROMPT = """You read one email for a personal calendar assistant. Decide what the email means for the user's calendar and extract concrete items.

User: {profile}
User email: {user_email}
Time zone: {tz}

Relationship labels. Pick exactly one:
- registered: the user already signed up, bought a ticket, booked, or was confirmed. Confirmations, tickets, receipts, appointment confirmations, and reminders for something confirmed earlier.
- personal: a real person wrote to the user about a concrete plan. Friends, family, colleagues, a professor writing one to one.
- invited: the user is invited by name to a specific meeting or event by a person or a small group. Calendar invites, interview scheduling, "can you join us Thursday".
- course: official communication for a class the user takes. Exam dates, deadlines, review sessions, lecture changes, assignments.
- informational: an organization tells the user about events the user has not signed up for. Club announcements, department newsletters, "you're invited" sent to a list.
- promotional: marketing, sales, sponsored events, calls to register.
- none: no calendar meaning at all.

Rules:
1. Mass invitations are informational or promotional, never invited. "You're invited!" to a list is not an invitation to the user.
2. Only extract events with a specific date. Skip "every Tuesday" recurrences unless one dated occurrence is named.
3. Resolve relative dates such as "this Friday" or "tomorrow" from the email's sent date.
4. Times without a zone are in the user's time zone. Output ISO 8601 with the offset.
5. A deadline is an event with kind "deadline". Its start is the due time. "11:59 PM" is a time, not all-day.
6. Confidence is about the event: is it real, specific, and something the user should see on the calendar?
7. Tasks are things the user must do before a date: submit, read, prepare, bring. Keep them short.
8. Do not invent details. Leave a field null when the email does not say.
9. If the email changes or cancels an event the user already had, say so with is_update or is_cancellation."""


def build_prompt(mail: ParsedEmail, triage: Triage, settings: Settings) -> str:
    hints = triage.hints
    yes_no = lambda flag: "yes" if flag else "no"  # noqa: E731
    lines = [
        f"Email sent: {fmt_local(mail.date, settings.tz)} ({settings.timezone})",
        f"From: {mail.from_name} <{mail.from_email}>".strip(),
        f"To: {', '.join(mail.to) or '(not shown)'}",
        f"Subject: {mail.subject or '(no subject)'}",
        f"Gmail category: {hints.get('gmail_category') or 'none'}",
        f"Bulk-mail headers: {yes_no(hints.get('bulk'))}",
        f"Trusted sender domain: {yes_no(hints.get('trusted_sender'))}",
        f"Addressed directly to the user: {yes_no(hints.get('direct_to_me'))}",
    ]
    if mail.attachments:
        lines.append(f"Attachments: {', '.join(mail.attachments)}")
    body = mail.body_text[:BODY_FOR_MODEL]
    if len(mail.body_text) > BODY_FOR_MODEL:
        body += "\n[truncated]"
    lines += ["", "Body:", body]
    return "\n".join(lines)


def system_prompt(settings: Settings) -> str:
    return SYSTEM_PROMPT.format(
        profile=settings.user_profile or "a student",
        user_email=settings.user_email or "unknown",
        tz=settings.timezone,
    )


def extract(mail: ParsedEmail, triage: Triage, settings: Settings, backend: LLMBackend) -> Extraction:
    return backend.structured(
        system=system_prompt(settings),
        prompt=build_prompt(mail, triage, settings),
        schema=Extraction,
    )
