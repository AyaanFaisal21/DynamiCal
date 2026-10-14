"""Pull new mail from Gmail and run it through the pipeline."""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..dates import now_utc
from ..db import Database
from ..ingest.pipeline import IngestReport, Pipeline
from ..llm.base import LLMBackend
from ..models import Message, SyncState
from .auth import load_credentials
from .client import GmailClient, HistoryExpired
from .parse import parse_rfc822

HISTORY_KEY = "gmail_history_id"
LAST_SYNC_KEY = "last_sync_at"
EMAIL_KEY = "gmail_address"


def get_state(s: Session, key: str) -> str | None:
    row = s.get(SyncState, key)
    return row.value if row else None


def set_state(s: Session, key: str, value: str) -> None:
    row = s.get(SyncState, key)
    if row is None:
        s.add(SyncState(key=key, value=value))
    else:
        row.value = value
        row.updated_at = now_utc()


def sync_gmail(
    db: Database,
    settings: Settings,
    backend: LLMBackend | None,
    *,
    days: int | None = None,
    max_messages: int | None = None,
    full: bool = False,
    log=print,
) -> IngestReport:
    creds = load_credentials(settings.gmail_credentials, settings.gmail_token, interactive=False)
    client = GmailClient(creds)
    profile = client.profile()
    address = str(profile.get("emailAddress", "")).lower()
    if address and not settings.user_email:
        settings = settings.model_copy(update={"user_email": address})

    with db.session() as s:
        last_history = get_state(s, HISTORY_KEY)

    ids: list[str] = []
    newest: str | None = None
    if last_history and not full:
        try:
            ids, newest = client.added_since(last_history)
            log(f"history since {last_history}: {len(ids)} new message(s)")
        except HistoryExpired:
            log("gmail history expired, doing a full query")
            last_history = None
    if not last_history or full:
        query = _with_days(settings.gmail_query, days)
        ids = client.list_message_ids(query, max_messages or settings.gmail_max_messages)
        newest = str(profile.get("historyId") or "")
        log(f"query {query!r}: {len(ids)} message(s)")

    with db.session() as s:
        known: set[str] = set()
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            known.update(s.scalars(select(Message.id).where(Message.id.in_(chunk))).all())
    fresh = [i for i in ids if i not in known]
    log(f"{len(fresh)} not seen before")

    mails = []
    for n, message_id in enumerate(fresh, 1):
        raw = client.fetch_raw(message_id)
        mails.append(parse_rfc822(raw.raw, message_id=raw.id, thread_id=raw.thread_id, labels=raw.labels))
        if n % 25 == 0:
            log(f"fetched {n}/{len(fresh)}")

    report = Pipeline(db, settings, backend).ingest(mails)

    with db.session() as s:
        if newest:
            set_state(s, HISTORY_KEY, newest)
        set_state(s, LAST_SYNC_KEY, now_utc().isoformat())
        if address:
            set_state(s, EMAIL_KEY, address)
    return report


def _with_days(query: str, days: int | None) -> str:
    if days is None:
        return query
    if re.search(r"newer_than:\d+d", query):
        return re.sub(r"newer_than:\d+d", f"newer_than:{days}d", query)
    return f"newer_than:{days}d {query}".strip()


def last_sync(db: Database) -> datetime | None:
    with db.session() as s:
        value = get_state(s, LAST_SYNC_KEY)
    return datetime.fromisoformat(value) if value else None
