"""One place that knows how healthy the app is. Used by the API and the CLI."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from . import __version__
from .config import Settings
from .db import Database
from .llm.base import LLMBackend
from .models import Event, Message, SyncState, Task


def collect_status(db: Database, settings: Settings, backend: LLMBackend | None) -> dict:
    with db.session() as s:
        event_counts = dict(s.execute(select(Event.status, func.count()).group_by(Event.status)).all())
        message_counts = dict(s.execute(select(Message.status, func.count()).group_by(Message.status)).all())
        open_tasks = s.scalar(select(func.count()).select_from(Task).where(Task.status == "open")) or 0
        last_sync = s.get(SyncState, "last_sync_at")
        gmail_address = s.get(SyncState, "gmail_address")

    model_name = None
    if backend is not None:
        model_name = getattr(backend, "model", None)

    return {
        "version": __version__,
        "timezone": settings.timezone,
        "user_email": settings.user_email or (gmail_address.value if gmail_address else None),
        "llm": {
            "provider": settings.llm_provider,
            "enabled": backend is not None,
            "model": model_name,
        },
        "gmail": {
            "authorized": settings.gmail_token.exists(),
            "credentials_present": settings.gmail_credentials.exists(),
            "last_sync": last_sync.value if last_sync else None,
            "query": settings.gmail_query,
        },
        "sync_interval_minutes": settings.sync_interval_minutes,
        "counts": {
            "events": {k: int(v) for k, v in event_counts.items()},
            "messages": {k: int(v) for k, v in message_counts.items()},
            "open_tasks": int(open_tasks),
        },
        "now": datetime.now().astimezone().isoformat(),
    }
