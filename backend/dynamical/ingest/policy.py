"""Turn a classification into one of four actions: add, propose, drop, cancel.

This is where "smart about what it adds" lives. The model labels; the policy
decides. Thresholds come from settings so the user can tune them.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from .ics import IcsEvent

COMMITTED = ("registered", "personal", "invited", "course")


@dataclass
class Decision:
    action: str  # add | propose | drop | cancel
    reason: str

    @property
    def status(self) -> str | None:
        return {"add": "confirmed", "propose": "proposed"}.get(self.action)


def decide_event(relationship: str, confidence: float, hints: dict, settings: Settings) -> Decision:
    if relationship in ("promotional", "none"):
        return Decision("drop", f"{relationship} email")

    if relationship == "informational":
        if confidence >= settings.propose_threshold:
            return Decision("propose", "announcement from an organization, no registration on record")
        return Decision("drop", f"informational, confidence {confidence:.2f} too low")

    if relationship not in COMMITTED:
        return Decision("drop", f"unknown relationship {relationship!r}")

    if relationship == "invited" and hints.get("bulk") and not hints.get("direct_to_me"):
        return Decision("propose", "invitation arrived as bulk mail")

    threshold = settings.auto_add_threshold
    if relationship == "course" and hints.get("trusted_sender"):
        threshold = min(threshold, 0.6)

    if confidence >= threshold:
        return Decision("add", f"{relationship}, confidence {confidence:.2f}")
    if confidence >= settings.propose_threshold:
        return Decision("propose", f"{relationship}, confidence {confidence:.2f} below auto-add threshold")
    return Decision("drop", f"{relationship}, confidence {confidence:.2f} too low")


def decide_ics(ics: IcsEvent, hints: dict, settings: Settings) -> Decision:
    if ics.cancelled:
        return Decision("cancel", "calendar cancellation")

    method = (ics.method or "").upper()
    user = settings.user_email_lower
    is_attendee = bool(user) and user in ics.attendees

    if method == "REQUEST":
        if is_attendee or hints.get("direct_to_me"):
            return Decision("add", "calendar invitation addressed to the user")
        return Decision("propose", "calendar invitation, user not listed as an attendee")
    if method == "REPLY":
        return Decision("drop", "reply to an invitation, not an event")

    # PUBLISH or no method: a calendar file was attached.
    if hints.get("bulk"):
        return Decision("propose", "calendar file inside bulk mail")
    if hints.get("trusted_sender") or hints.get("direct_to_me") or hints.get("personal_category"):
        return Decision("add", "calendar file from a trusted or personal sender")
    return Decision("propose", "calendar file from an unknown sender")
