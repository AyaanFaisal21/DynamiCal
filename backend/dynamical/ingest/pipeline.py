"""Run emails through triage, extraction, policy, and upsert. Record every step."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from ..config import Settings
from ..dates import local_midnight, now_utc, parse_date, parse_datetime
from ..db import Database
from ..gmail.parse import ParsedEmail
from ..llm.base import LLMBackend, LLMError
from ..models import Message
from .extract import Extraction, extract
from .ics import parse_ics
from .policy import COMMITTED, decide_event, decide_ics
from .triage import Triage, triage
from .upsert import upsert_event, upsert_task

DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class IngestReport:
    seen: int = 0
    new: int = 0
    skipped: int = 0
    from_ics: int = 0
    extracted: int = 0
    waiting_for_model: int = 0
    errors: int = 0
    events_created: int = 0
    events_updated: int = 0
    events_cancelled: int = 0
    proposed: int = 0
    dropped: int = 0
    tasks_created: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    def summary(self) -> str:
        return (
            f"{self.seen} seen, {self.new} new, {self.skipped} skipped, {self.from_ics} from calendar files, "
            f"{self.extracted} extracted, {self.waiting_for_model} waiting for a model, {self.errors} errors. "
            f"Events: {self.events_created} created, {self.events_updated} updated, "
            f"{self.events_cancelled} cancelled, {self.proposed} proposed, {self.dropped} dropped. "
            f"Tasks: {self.tasks_created} created."
        )


class Pipeline:
    def __init__(self, db: Database, settings: Settings, backend: LLMBackend | None):
        self.db = db
        self.settings = settings
        self.backend = backend

    # -- entry points --------------------------------------------------------------

    def ingest(self, mails: Iterable[ParsedEmail], *, reprocess: bool = False) -> IngestReport:
        report = IngestReport()
        for mail in mails:
            report.seen += 1
            with self.db.session() as s:
                self._one(s, mail, report, reprocess=reprocess)
        return report

    def process_pending(self) -> IngestReport:
        """Retry messages that waited for a model or hit an error."""
        from sqlalchemy import select

        report = IngestReport()
        with self.db.session() as s:
            pending = s.scalars(select(Message).where(Message.status.in_(("new", "error")))).all()
            mails = [self._rehydrate(m) for m in pending]
        for mail in mails:
            report.seen += 1
            with self.db.session() as s:
                self._one(s, mail, report, reprocess=True)
        return report

    # -- one message -----------------------------------------------------------------

    def _one(self, s: Session, mail: ParsedEmail, report: IngestReport, *, reprocess: bool) -> None:
        msg = s.get(Message, mail.message_id)
        if msg is not None and msg.status in ("processed", "skipped") and not reprocess:
            return
        if msg is None:
            msg = Message(id=mail.message_id)
            s.add(msg)
            report.new += 1
        self._store(msg, mail)

        result = triage(mail, self.settings)
        msg.triage_decision = result.decision
        msg.triage_score = result.score
        msg.triage_reasons = json.dumps(result.reasons)

        if result.decision == "skip":
            msg.status = "skipped"
            msg.processed_at = now_utc()
            report.skipped += 1
            return

        if result.decision == "ics":
            self._from_ics(s, mail, msg, result, report)
            msg.status = "processed"
            msg.processed_at = now_utc()
            report.from_ics += 1
            return

        if self.backend is None:
            msg.status = "new"
            msg.error = "no model configured"
            report.waiting_for_model += 1
            return

        try:
            extraction = extract(mail, result, self.settings, self.backend)
        except LLMError as exc:
            msg.status = "error"
            msg.error = str(exc)[:1000]
            report.errors += 1
            report.notes.append(f"{mail.subject[:60]}: {exc}")
            return
        except Exception as exc:  # a bug in a backend should not stop the sync
            msg.status = "error"
            msg.error = f"{type(exc).__name__}: {exc}"[:1000]
            report.errors += 1
            report.notes.append(f"{mail.subject[:60]}: {exc}")
            return

        msg.extraction_json = extraction.model_dump_json()
        msg.error = None
        self._apply(s, mail, msg, result, extraction, report)
        msg.status = "processed"
        msg.processed_at = now_utc()
        report.extracted += 1

    def _store(self, msg: Message, mail: ParsedEmail) -> None:
        msg.thread_id = mail.thread_id
        msg.subject = mail.subject
        msg.from_name = mail.from_name
        msg.from_email = mail.from_email
        msg.to_header = ", ".join(mail.to)
        msg.date = mail.date
        msg.snippet = mail.snippet
        msg.body_text = mail.body_text
        msg.labels = ",".join(mail.labels)
        msg.has_ics = mail.has_ics
        msg.ics_text = mail.ics_text
        msg.list_unsubscribe = mail.list_unsubscribe
        msg.list_id = mail.list_id

    def _rehydrate(self, msg: Message) -> ParsedEmail:
        return ParsedEmail(
            message_id=msg.id,
            thread_id=msg.thread_id,
            subject=msg.subject,
            from_name=msg.from_name,
            from_email=msg.from_email,
            to=[a.strip() for a in msg.to_header.split(",") if a.strip()],
            cc=[],
            date=msg.date,
            body_text=msg.body_text,
            snippet=msg.snippet,
            list_unsubscribe=msg.list_unsubscribe,
            list_id=msg.list_id,
            precedence=None,
            auto_submitted=None,
            has_ics=msg.has_ics,
            ics_text=msg.ics_text,
            labels=[l for l in msg.labels.split(",") if l],
        )

    # -- calendar attachments --------------------------------------------------------

    def _from_ics(self, s: Session, mail: ParsedEmail, msg: Message, result: Triage, report: IngestReport) -> None:
        for ics in parse_ics(mail.ics_text or "", self.settings.tz):
            decision = decide_ics(ics, result.hints, self.settings)
            if decision.action == "drop":
                report.dropped += 1
                continue
            tz = self._zone(ics.tz_name)
            method = (ics.method or "").upper()
            relationship = "invited" if method == "REQUEST" else "registered"
            outcome = upsert_event(
                s,
                title=ics.summary,
                start=ics.start,
                end=ics.end,
                tz=tz,
                status=decision.status or "confirmed",
                source="ics",
                all_day=ics.all_day,
                kind="meeting" if method == "REQUEST" else "event",
                location=ics.location,
                description=ics.description,
                source_message_id=msg.id,
                thread_id=mail.thread_id,
                relationship=relationship,
                confidence=1.0 if method == "REQUEST" else 0.9,
                rationale=decision.reason,
                external_id=ics.uid,
                is_cancellation=decision.action == "cancel",
                exclude_message_id=msg.id,
            )
            self._count(outcome.action, decision.action, report)

    # -- model extraction ------------------------------------------------------------

    def _apply(
        self,
        s: Session,
        mail: ParsedEmail,
        msg: Message,
        result: Triage,
        extraction: Extraction,
        report: IngestReport,
    ) -> None:
        tz = self.settings.tz
        created_events = []
        for item in extraction.events:
            start, end, all_day = self._times(item.start, item.end, item.all_day, item.kind)
            if start is None:
                report.notes.append(f"{mail.subject[:60]}: unparseable start {item.start!r}")
                continue
            decision = decide_event(extraction.relationship, item.confidence, result.hints, self.settings)
            if decision.action == "drop":
                report.dropped += 1
                continue
            outcome = upsert_event(
                s,
                title=item.title,
                start=start,
                end=end,
                tz=tz,
                status=decision.status or "proposed",
                source="email",
                all_day=all_day,
                kind=item.kind,
                location=item.location,
                description=item.description or extraction.summary,
                source_message_id=msg.id,
                thread_id=mail.thread_id,
                relationship=extraction.relationship,
                confidence=item.confidence,
                rationale=f"{decision.reason}. {extraction.rationale}".strip(),
                is_cancellation=item.is_cancellation,
                is_update=item.is_update,
                exclude_message_id=msg.id,
            )
            self._count(outcome.action, decision.action, report)
            if outcome.event is not None and outcome.action in ("created", "updated", "unchanged"):
                created_events.append(outcome.event)

        if extraction.relationship not in COMMITTED:
            return
        for task in extraction.tasks:
            due = parse_datetime(task.due, tz) if task.due else None
            linked = None
            if due is not None:
                for ev in created_events:
                    if abs(ev.start - due) <= timedelta(days=1):
                        linked = ev.id
                        break
            elif created_events:
                linked = created_events[0].id
            _, created = upsert_task(
                s,
                title=task.title,
                due=due,
                kind=task.kind,
                details=task.details,
                event_id=linked,
                source_message_id=msg.id,
                tz=tz,
            )
            if created:
                report.tasks_created += 1

    def _times(self, start_text: str, end_text: str | None, all_day: bool, kind: str):
        tz = self.settings.tz
        if all_day or DATE_ONLY.match(start_text.strip()):
            day = parse_date(start_text)
            if day is None:
                return None, None, True
            start = local_midnight(day, tz)
            end_day = parse_date(end_text) if end_text else None
            end = local_midnight(end_day, tz) if end_day and end_day > day else start + timedelta(days=1)
            return start, end, True
        start = parse_datetime(start_text, tz)
        if start is None:
            return None, None, False
        end = parse_datetime(end_text, tz) if end_text else None
        if end is not None and end <= start:
            end = None
        if end is None:
            end = start if kind == "deadline" else start + timedelta(hours=1)
        return start, end, False

    @staticmethod
    def _count(outcome: str, action: str, report: IngestReport) -> None:
        if outcome == "created":
            report.events_created += 1
            if action == "propose":
                report.proposed += 1
        elif outcome == "updated":
            report.events_updated += 1
        elif outcome == "cancelled":
            report.events_cancelled += 1

    def _zone(self, name: str | None) -> ZoneInfo:
        if name:
            try:
                return ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError):
                pass
        return self.settings.tz
