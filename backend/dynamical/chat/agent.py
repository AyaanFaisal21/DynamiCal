"""The side-panel assistant: a bounded tool-calling loop with stored history."""

from __future__ import annotations

import json
import re

from sqlalchemy import select

from ..config import Settings
from ..dates import day_bounds, fmt_range, now_utc, parse_date, to_local
from ..db import Database
from ..llm.base import ChatResult, ChatTurn, LLMBackend, LLMError
from ..models import ChatMessage, Event
from .tools import ToolContext, build_tools

HISTORY_TURNS = 20

SYSTEM = """You are DynamiCal, a calendar assistant for one user.

Now: {now} ({tz}). Today is {today}.
User: {profile}

You answer questions about the user's calendar, deadlines, tasks, and free time.
Rules:
- Look things up with the tools before answering. Never guess dates or times.
- Dates and times in tool results are already in the user's time zone. Repeat them as given.
- When asked what to do with free time, check upcoming exams, deadlines, and open tasks, then suggest specific preparation that fits the free slots.
- Items marked proposed are waiting for the user's review. Say so when you mention them.
- Only create blocks or tasks when the user clearly asks. Confirm what you created.
- Be brief. Plain text, short lines. No markdown tables."""


def system_prompt(settings: Settings, now) -> str:
    local = to_local(now, settings.tz)
    return SYSTEM.format(
        now=local.strftime("%A %B %d, %Y %I:%M %p").replace(" 0", " "),
        tz=settings.timezone,
        today=local.date().isoformat(),
        profile=settings.user_profile or "a student",
    )


def load_history(db: Database, limit: int = HISTORY_TURNS) -> list[ChatTurn]:
    with db.session() as s:
        rows = s.scalars(select(ChatMessage).order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(limit)).all()
    return [ChatTurn(role=r.role, content=r.content) for r in reversed(rows)]


def answer(db: Database, settings: Settings, backend: LLMBackend | None, message: str) -> tuple[ChatMessage, ChatResult]:
    """Store the user turn, get a reply, store it, and return both the row and the result."""
    now = now_utc()
    history = load_history(db) + [ChatTurn(role="user", content=message)]

    if backend is None:
        result = fallback(db, settings, message)
    else:
        ctx = ToolContext(db=db, settings=settings, now=now)
        try:
            result = backend.chat(system=system_prompt(settings, now), history=history, tools=build_tools(ctx))
        except LLMError as exc:
            result = ChatResult(text=f"The model call failed: {exc}")
        if not result.text.strip():
            result.text = "I could not come up with an answer. Try asking in a different way."

    with db.session() as s:
        s.add(ChatMessage(role="user", content=message, created_at=now))
        reply = ChatMessage(
            role="assistant",
            content=result.text,
            tool_log=json.dumps([{"name": c.name, "args": c.args} for c in result.tool_calls]) if result.tool_calls else None,
        )
        s.add(reply)
        s.flush()
    return reply, result


_DATE_WORDS = re.compile(r"\b(today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4}-\d{2}-\d{2}|\w+ \d{1,2})\b", re.I)


def fallback(db: Database, settings: Settings, message: str) -> ChatResult:
    """No model configured: list the events for a day mentioned in the message."""
    today = to_local(now_utc(), settings.tz).date()
    target = None
    match = _DATE_WORDS.search(message)
    if match:
        word = match.group(1).lower()
        if word == "today":
            target = today
        elif word == "tomorrow":
            target = today.fromordinal(today.toordinal() + 1)
        elif word == "yesterday":
            target = today.fromordinal(today.toordinal() - 1)
        else:
            target = parse_date(word)
    if target is None:
        return ChatResult(
            text=(
                "No model is configured, so I can only list days. Ask for a date, for example "
                "'what do I have on 2026-10-15'. Set LLM_PROVIDER in .env to enable full chat."
            )
        )
    start, end = day_bounds(target, settings.tz)
    with db.session() as s:
        rows = s.scalars(
            select(Event).where(Event.start < end, Event.end > start, Event.status == "confirmed").order_by(Event.start)
        ).all()
    if not rows:
        return ChatResult(text=f"Nothing on the calendar for {target.isoformat()}.")
    lines = [f"{target.strftime('%A %B %d')}:"]
    lines += [f"- {fmt_range(e.start, e.end, settings.tz, e.all_day)}: {e.title}" for e in rows]
    return ChatResult(text="\n".join(lines))
