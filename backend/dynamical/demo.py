"""Sample data for trying the app without Gmail or a model.

The emails are the synthetic fixtures under backend/tests/fixtures/emails. The
canned extractions stand in for what the model would return for each one.
Tests use the same data, so the demo and the tests cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path

from .config import ROOT, Settings
from .db import Database
from .gmail.parse import ParsedEmail, parse_eml_file
from .ingest.extract import ExtractedEvent, ExtractedTask, Extraction
from .ingest.pipeline import IngestReport, Pipeline
from .llm.base import ChatResult, ChatTurn, ToolSpec, run_tool

FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "emails"

# Labels Gmail would attach to each fixture. The parser cannot know these.
LABELS: dict[str, list[str]] = {
    "01_eventbrite_confirmation": ["INBOX", "CATEGORY_UPDATES"],
    "02_newsletter_promo": ["INBOX", "CATEGORY_PROMOTIONS"],
    "03_friend_dinner": ["INBOX", "CATEGORY_PERSONAL"],
    "04_gcal_invite": ["INBOX"],
    "05_course_exam": ["INBOX", "CATEGORY_FORUMS"],
    "06_org_mass_invite": ["INBOX", "CATEGORY_UPDATES"],
    "07_canvas_assignment": ["INBOX", "CATEGORY_UPDATES"],
    "08_health_appointment": ["INBOX", "CATEGORY_UPDATES"],
    "09_dept_colloquium": ["INBOX", "CATEGORY_FORUMS"],
}

# Keyed by a phrase that appears in the prompt built for that email.
CANNED: dict[str, Extraction] = {
    "Your ticket for Rutgers AI Society": Extraction(
        relationship="registered",
        summary="Ticket confirmation for the hackathon kickoff.",
        rationale="The user holds a ticket.",
        events=[
            ExtractedEvent(
                title="Rutgers AI Society: Fall Hackathon Kickoff",
                start="2026-10-23T18:00:00-04:00",
                end="2026-10-23T21:00:00-04:00",
                location="Busch Student Center",
                kind="event",
                confidence=0.95,
            )
        ],
    ),
    "dinner saturday?": Extraction(
        relationship="personal",
        summary="A friend proposes dinner on Saturday.",
        rationale="Written by a friend to the user.",
        events=[
            ExtractedEvent(
                title="Dinner with Priya", start="2026-10-18T19:00:00-04:00", location="Stuff Yer Face", kind="social", confidence=0.8
            )
        ],
        tasks=[ExtractedTask(title="Reply to Priya about dinner", due="2026-10-15", kind="todo")],
    ),
    "Midterm 2 date and logistics": Extraction(
        relationship="course",
        summary="Midterm 2 date and a review session.",
        rationale="Official course email.",
        events=[
            ExtractedEvent(
                title="CS 211 Midterm 2",
                start="2026-10-28T20:40:00-04:00",
                end="2026-10-28T22:00:00-04:00",
                location="Hill 114",
                kind="exam",
                description="Covers chapters 4 through 6: pointers, memory, and assembly basics. Bring a student ID.",
                confidence=0.95,
            ),
            ExtractedEvent(
                title="CS 211 Midterm 2 review session",
                start="2026-10-26T19:00:00-04:00",
                location="CoRE 101",
                kind="class",
                confidence=0.85,
            ),
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
    "Verified GPU kernels in practice": Extraction(
        relationship="informational",
        summary="The department announces a colloquium talk.",
        rationale="Sent to the whole undergraduate list. No sign-up on record.",
        events=[
            ExtractedEvent(
                title="Colloquium: Verified GPU kernels in practice",
                start="2026-10-30T14:00:00-04:00",
                end="2026-10-30T15:15:00-04:00",
                location="CoRE 431",
                kind="event",
                description="Department talk by Dr. Lena Ortiz. Open to all undergraduates.",
                confidence=0.85,
            )
        ],
    ),
    "Appointment confirmation": Extraction(
        relationship="registered",
        summary="A confirmed health appointment.",
        rationale="Confirmation of a booking the user made.",
        events=[
            ExtractedEvent(
                title="Student Health appointment with Dr. Alvarez",
                start="2026-10-17T10:30:00-04:00",
                location="Hurtado Health Center",
                kind="appointment",
                confidence=0.95,
            )
        ],
    ),
}


class CannedBackend:
    """Returns the canned extraction whose key appears in the prompt."""

    name = "canned"
    model = "canned-demo"

    def __init__(self, canned: dict[str, Extraction] | None = None, chat_plan: list[tuple[str, dict]] | None = None):
        self.canned = canned if canned is not None else CANNED
        self.chat_plan = chat_plan or []
        self.calls: list[str] = []

    def structured(self, *, system: str, prompt: str, schema):
        self.calls.append(prompt)
        for needle, extraction in self.canned.items():
            if needle in prompt:
                return extraction
        return Extraction(relationship="none", summary="nothing", rationale="no match", events=[], tasks=[])

    def chat(self, *, system: str, history: list[ChatTurn], tools: list[ToolSpec], max_rounds: int = 6) -> ChatResult:
        outputs = [run_tool(tools, name, args) for name, args in self.chat_plan]
        return ChatResult(text="\n".join(outputs) or "This is the demo backend. Configure a model for real answers.")


def demo_settings(settings: Settings) -> Settings:
    """The fixtures are addressed to a sample student. Match the identity to them."""
    return settings.model_copy(
        update={
            "user_email": "sam@scarlet.example.edu",
            "trusted_domains": "example.edu",
            "user_profile": settings.user_profile or "Undergraduate CS student.",
        }
    )


def load_fixtures(directory: Path = FIXTURES) -> list[ParsedEmail]:
    mails = []
    for path in sorted(directory.glob("*.eml")):
        mail = parse_eml_file(path, labels=LABELS.get(path.stem, ["INBOX"]))
        mail.thread_id = f"thread-{path.stem}"
        mails.append(mail)
    return mails


def seed(db: Database, settings: Settings) -> IngestReport:
    if not FIXTURES.exists():
        raise FileNotFoundError(f"fixtures not found at {FIXTURES}")
    return Pipeline(db, demo_settings(settings), CannedBackend()).ingest(load_fixtures())
