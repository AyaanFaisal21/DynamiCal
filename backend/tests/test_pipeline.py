from sqlalchemy import select

from dynamical.demo import CANNED
from dynamical.ingest.extract import ExtractedEvent, ExtractedTask, Extraction
from dynamical.ingest.pipeline import Pipeline
from dynamical.models import Event, Message, Task
from fake_backend import FakeBackend

ALL = [
    "01_eventbrite_confirmation",
    "02_newsletter_promo",
    "03_friend_dinner",
    "04_gcal_invite",
    "05_course_exam",
    "06_org_mass_invite",
    "07_canvas_assignment",
    "08_health_appointment",
    "09_dept_colloquium",
]

def test_full_run_is_selective_and_idempotent(db, settings, load):
    backend = FakeBackend(CANNED)
    pipeline = Pipeline(db, settings, backend)
    report = pipeline.ingest([load(n) for n in ALL])

    assert report.new == 9
    assert report.skipped == 2  # promo newsletter and the org blast never reach the model
    assert report.from_ics == 1
    assert report.extracted == 6
    assert len(backend.calls) == 6
    assert report.events_created == 8
    assert report.proposed == 1  # the department colloquium waits for review
    assert report.tasks_created == 3

    with db.session() as s:
        events = s.scalars(select(Event).order_by(Event.start)).all()
        assert [e.title for e in events] == [
            "CS 419 Project Sync",
            "Student Health appointment with Dr. Alvarez",
            "Dinner with Priya",
            "CS 344 Homework 4 due",
            "Rutgers AI Society: Fall Hackathon Kickoff",
            "CS 211 Midterm 2 review session",
            "CS 211 Midterm 2",
            "Colloquium: Verified GPU kernels in practice",
        ]
        assert [e.status for e in events] == ["confirmed"] * 7 + ["proposed"]
        invite = events[0]
        assert invite.source == "ics" and invite.external_id == "cs419sync20261015@google.com"
        deadline = next(e for e in events if e.kind == "deadline")
        assert deadline.end == deadline.start
        hw = s.scalars(select(Task).where(Task.kind == "assignment")).one()
        assert hw.event_id == deadline.id
        skipped = s.get(Message, load("02_newsletter_promo").message_id)
        assert skipped.status == "skipped" and skipped.triage_decision == "skip"

    # Running the same mail again touches nothing and asks the model nothing.
    again = pipeline.ingest([load(n) for n in ALL])
    assert again.new == 0 and again.events_created == 0 and again.tasks_created == 0
    assert len(backend.calls) == 6


def test_informational_becomes_a_proposal(db, settings, load):
    canned = {
        "Your ticket for Rutgers AI Society": Extraction(
            relationship="informational",
            summary="An org announces an event.",
            rationale="No sign-up on record.",
            events=[ExtractedEvent(title="Some org event", start="2026-10-23T18:00:00-04:00", confidence=0.9)],
            tasks=[ExtractedTask(title="should not be created", kind="todo")],
        )
    }
    report = Pipeline(db, settings, FakeBackend(canned)).ingest([load("01_eventbrite_confirmation")])
    assert report.proposed == 1 and report.tasks_created == 0
    with db.session() as s:
        assert s.scalars(select(Event)).one().status == "proposed"


def test_without_a_model_messages_wait_then_catch_up(db, settings, load):
    waiting = Pipeline(db, settings, None).ingest([load("01_eventbrite_confirmation"), load("04_gcal_invite")])
    assert waiting.waiting_for_model == 1 and waiting.from_ics == 1
    with db.session() as s:
        msg = s.get(Message, load("01_eventbrite_confirmation").message_id)
        assert msg.status == "new" and msg.error == "no model configured"

    caught_up = Pipeline(db, settings, FakeBackend(CANNED)).process_pending()
    assert caught_up.extracted == 1 and caught_up.events_created == 1
    with db.session() as s:
        assert s.get(Message, load("01_eventbrite_confirmation").message_id).status == "processed"


def test_cancellation_from_calendar_file(db, settings, load):
    pipeline = Pipeline(db, settings, None)
    invite = load("04_gcal_invite")
    pipeline.ingest([invite])
    cancel = load("04_gcal_invite")
    cancel.message_id = "cancel-1"
    cancel.ics_text = cancel.ics_text.replace("METHOD:REQUEST", "METHOD:CANCEL").replace("STATUS:CONFIRMED", "STATUS:CANCELLED")
    report = pipeline.ingest([cancel])
    assert report.events_cancelled == 1
    with db.session() as s:
        assert s.scalars(select(Event)).one().status == "cancelled"
