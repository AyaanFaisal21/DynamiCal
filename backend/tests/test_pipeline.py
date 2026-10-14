from sqlalchemy import select

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
]

CANNED = {
    "Your ticket for Rutgers AI Society": Extraction(
        relationship="registered",
        summary="Ticket confirmation for the hackathon kickoff.",
        rationale="The user holds a ticket.",
        events=[ExtractedEvent(title="Rutgers AI Society: Fall Hackathon Kickoff", start="2026-10-23T18:00:00-04:00", end="2026-10-23T21:00:00-04:00", location="Busch Student Center", kind="event", confidence=0.95)],
    ),
    "dinner saturday?": Extraction(
        relationship="personal",
        summary="A friend proposes dinner on Saturday.",
        rationale="Written by a friend to the user.",
        events=[ExtractedEvent(title="Dinner with Priya", start="2026-10-18T19:00:00-04:00", location="Stuff Yer Face", kind="social", confidence=0.8)],
        tasks=[ExtractedTask(title="Reply to Priya about dinner", due="2026-10-15", kind="todo")],
    ),
    "Midterm 2 date and logistics": Extraction(
        relationship="course",
        summary="Midterm 2 date and a review session.",
        rationale="Official course email.",
        events=[
            ExtractedEvent(title="CS 211 Midterm 2", start="2026-10-28T20:40:00-04:00", end="2026-10-28T22:00:00-04:00", location="Hill 114", kind="exam", confidence=0.95),
            ExtractedEvent(title="CS 211 Midterm 2 review session", start="2026-10-26T19:00:00-04:00", location="CoRE 101", kind="class", confidence=0.85),
        ],
        tasks=[ExtractedTask(title="Read chapter 6 before the review session", due="2026-10-26", kind="reading")],
    ),
    "Homework 4: Dynamic Programming": Extraction(
        relationship="course",
        summary="A new assignment with a due date.",
        rationale="Canvas notification for an enrolled course.",
        events=[ExtractedEvent(title="CS 344 Homework 4 due", start="2026-10-20T23:59:00-04:00", kind="deadline", confidence=0.9)],
        tasks=[ExtractedTask(title="CS 344 Homework 4: Dynamic Programming", due="2026-10-20T23:59:00-04:00", kind="assignment")],
    ),
    "Appointment confirmation": Extraction(
        relationship="registered",
        summary="A confirmed health appointment.",
        rationale="Confirmation of a booking the user made.",
        events=[ExtractedEvent(title="Student Health appointment with Dr. Alvarez", start="2026-10-17T10:30:00-04:00", location="Hurtado Health Center", kind="appointment", confidence=0.95)],
    ),
}


def test_full_run_is_selective_and_idempotent(db, settings, load):
    backend = FakeBackend(CANNED)
    pipeline = Pipeline(db, settings, backend)
    report = pipeline.ingest([load(n) for n in ALL])

    assert report.new == 8
    assert report.skipped == 2  # promo newsletter and the org blast never reach the model
    assert report.from_ics == 1
    assert report.extracted == 5
    assert len(backend.calls) == 5
    assert report.events_created == 7
    assert report.proposed == 0
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
        ]
        assert all(e.status == "confirmed" for e in events)
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
    assert len(backend.calls) == 5


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
