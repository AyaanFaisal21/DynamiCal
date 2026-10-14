from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from dynamical.ingest.upsert import normalise_title, upsert_event, upsert_task
from dynamical.models import Event, Message

NY = ZoneInfo("America/New_York")
START = datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc)


def _msg(s, mid, thread):
    s.add(Message(id=mid, thread_id=thread, date=START, subject="x"))
    s.flush()


def _upsert(s, **kw):
    base = dict(
        title="Hackathon Kickoff",
        start=START,
        end=START + timedelta(hours=3),
        tz=NY,
        status="confirmed",
        source="email",
        thread_id="t1",
        source_message_id="m1",
    )
    base.update(kw)
    return upsert_event(s, **base)


def test_normalise_title():
    assert normalise_title("Re: Fwd: Reminder: Hackathon Kickoff!") == "hackathon kickoff"
    assert normalise_title("Invitation: CS 419 Project Sync @ Wed Oct 15, 2026 4pm - 5pm (EDT)") == "cs 419 project sync"
    assert normalise_title("[cs211] Midterm 2") == "midterm 2"


def test_same_event_twice_is_one_row(db):
    with db.session() as s:
        _msg(s, "m1", "t1")
        assert _upsert(s).action == "created"
        assert _upsert(s).action == "unchanged"
        assert _upsert(s, title="Reminder: Hackathon Kickoff").action == "unchanged"
        assert len(s.scalars(select(Event)).all()) == 1


def test_time_change_in_same_thread_updates(db):
    with db.session() as s:
        _msg(s, "m1", "t1")
        _msg(s, "m2", "t1")
        _upsert(s)
        moved = START + timedelta(days=1)
        result = _upsert(s, title="Hackathon Kickoff moved to Friday", start=moved, source_message_id="m2")
        assert result.action == "updated"
        assert len(s.scalars(select(Event)).all()) == 1
        assert result.event.start == moved
        assert result.event.source_message_id == "m2"


def test_cancellation(db):
    with db.session() as s:
        _msg(s, "m1", "t1")
        _upsert(s)
        result = _upsert(s, is_cancellation=True)
        assert result.action == "cancelled"
        assert result.event.status == "cancelled"
        # A cancellation for something we never had creates nothing.
        assert _upsert(s, title="Other thing", thread_id="t9", is_cancellation=True).action == "skipped"


def test_rejected_is_not_resurrected(db):
    with db.session() as s:
        _msg(s, "m1", "t1")
        ev = _upsert(s, status="proposed").event
        ev.status = "rejected"
        s.flush()
        assert _upsert(s).action == "skipped"
        assert ev.status == "rejected"


def test_status_only_moves_up(db):
    with db.session() as s:
        _msg(s, "m1", "t1")
        ev = _upsert(s, status="proposed").event
        assert _upsert(s, status="confirmed").event.status == "confirmed"
        assert _upsert(s, status="proposed").event.status == "confirmed"
        assert ev.status == "confirmed"


def test_external_id_wins_over_title(db):
    with db.session() as s:
        _msg(s, "m1", "t1")
        a = _upsert(s, external_id="uid-1", thread_id=None).event
        b = _upsert(s, title="Renamed completely", external_id="uid-1", thread_id=None).event
        assert a.id == b.id
        assert b.title == "Renamed completely"


def test_task_dedupe(db):
    with db.session() as s:
        _msg(s, "m1", "t1")
        due = START
        _, created = upsert_task(s, title="Read chapter 6", due=due, tz=NY)
        _, created_again = upsert_task(s, title="Read Chapter 6!", due=due, tz=NY)
        assert created and not created_again


def test_two_events_from_one_email_stay_distinct(db):
    with db.session() as s:
        _msg(s, "m1", "t1")
        exam = _upsert(s, title="CS 211 Midterm 2", exclude_message_id="m1").event
        review = _upsert(
            s,
            title="CS 211 Midterm 2 review session",
            start=START - timedelta(days=2),
            end=START - timedelta(days=2) + timedelta(hours=1),
            exclude_message_id="m1",
        ).event
        assert exam.id != review.id
        assert len(s.scalars(select(Event)).all()) == 2


def test_update_flag_allows_a_looser_title_match(db):
    with db.session() as s:
        _msg(s, "m1", "t1")
        _msg(s, "m2", "t1")
        _upsert(s, title="Project sync")
        moved = START + timedelta(days=2)
        strict = _upsert(s, title="Project sync with the whole team", start=moved, source_message_id="m2")
        assert strict.action == "created"
        s.delete(strict.event)
        s.flush()
        loose = _upsert(s, title="Project sync with the whole team", start=moved, source_message_id="m2", is_update=True)
        assert loose.action == "updated"
