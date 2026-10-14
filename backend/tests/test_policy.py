import pytest

from dynamical.ingest.ics import IcsEvent
from dynamical.ingest.policy import decide_event, decide_ics
from dynamical.dates import now_utc

NO_HINTS = {"bulk": False, "direct_to_me": True, "trusted_sender": False, "personal_category": False}
BULK = {"bulk": True, "direct_to_me": False, "trusted_sender": False, "personal_category": False}


@pytest.mark.parametrize(
    "relationship,confidence,hints,action",
    [
        ("registered", 0.9, NO_HINTS, "add"),
        ("registered", 0.5, NO_HINTS, "propose"),
        ("registered", 0.2, NO_HINTS, "drop"),
        ("personal", 0.8, NO_HINTS, "add"),
        ("invited", 0.9, NO_HINTS, "add"),
        ("invited", 0.9, BULK, "propose"),  # "you're invited" blast
        ("course", 0.65, {**NO_HINTS, "trusted_sender": True}, "add"),
        ("course", 0.65, NO_HINTS, "propose"),
        ("informational", 0.9, NO_HINTS, "propose"),
        ("informational", 0.3, NO_HINTS, "drop"),
        ("promotional", 0.99, NO_HINTS, "drop"),
        ("none", 0.99, NO_HINTS, "drop"),
    ],
)
def test_decide_event(settings, relationship, confidence, hints, action):
    assert decide_event(relationship, confidence, hints, settings).action == action


def _ics(method, attendees=(), status=None):
    return IcsEvent(
        uid="u",
        summary="s",
        start=now_utc(),
        end=None,
        all_day=False,
        location=None,
        description=None,
        status=status,
        method=method,
        organizer=None,
        attendees=list(attendees),
    )


def test_decide_ics(settings):
    me = settings.user_email
    assert decide_ics(_ics("REQUEST", [me]), BULK, settings).action == "add"
    assert decide_ics(_ics("REQUEST"), BULK, settings).action == "propose"
    assert decide_ics(_ics("CANCEL", [me]), NO_HINTS, settings).action == "cancel"
    assert decide_ics(_ics("REQUEST", [me], status="CANCELLED"), NO_HINTS, settings).action == "cancel"
    assert decide_ics(_ics("REPLY"), NO_HINTS, settings).action == "drop"
    assert decide_ics(_ics(None), BULK, settings).action == "propose"
    assert decide_ics(_ics(None), {**NO_HINTS, "trusted_sender": True}, settings).action == "add"
