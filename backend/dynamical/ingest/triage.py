"""Rule-based first pass over an email.

This stage runs on every message and costs nothing. Its job is to drop clear
bulk mail before the model sees it, to route calendar attachments to the ICS
reader, and to collect hints the policy stage uses later.

Scores are integer weights. Gmail's own category is the strongest signal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import Settings
from ..gmail.parse import ParsedEmail
from .ics import parse_ics

SKIP_AT_OR_BELOW = -4

# Words that suggest the user has a real stake in the email.
POSITIVE_PATTERNS = [
    r"\bconfirm(ed|ation)\b",
    r"\byou'?re (registered|confirmed|all set|in|going|booked)\b",
    r"\byou are (registered|confirmed|all set|going|booked)\b",
    r"\bthanks? for (registering|signing up|booking|your order)\b",
    r"\byour (ticket|order|booking|reservation|appointment|registration|rsvp|seat|spot|interview)s?\b",
    r"\bticket\b",
    r"\binterview\b",
    r"\bappointment\b",
    r"\b(mid-?term|final exam|exam|quiz|test)\b",
    r"\b(assignment|homework|problem set|project|lab)\b",
    r"\b(due|deadline|submit(ted)?|submission)\b",
    r"\boffice hours\b",
    r"\b(rescheduled|moved to|time change|cancel+ed|postponed)\b",
    r"\bmeeting\b",
    r"\bsee you (at|on|there|then)\b",
    r"\binvitation:\b",
    r"\baccepted:\b",
]

# Words that suggest marketing or a broadcast.
NEGATIVE_PATTERNS = [
    r"\bnewsletter\b",
    r"\bdigest\b",
    r"\bunsubscribe\b",
    r"\bdon'?t miss\b",
    r"\bjoin us\b",
    r"\bregister (now|today|here)\b",
    r"\bsign up (now|today|here)\b",
    r"\bsave the date\b",
    r"\blimited (seats|spots|time)\b",
    r"\b\d{1,2}% off\b",
    r"\b(sale|promo|discount|deal)s?\b",
    r"\bupcoming events\b",
    r"\bthis week (at|in|on)\b",
    r"\bweekly (update|roundup|round-up|events)\b",
    r"\bfree (food|pizza|snacks|swag)\b",
    r"\bapply (now|today)\b",
    r"\bview (in|this email in) (your )?browser\b",
]

NOREPLY = re.compile(r"^(no-?reply|do-?not-?reply|noreply|notifications?|mailer-daemon|bounce|alerts?)[@.+-]", re.I)
UNDISCLOSED = re.compile(r"undisclosed", re.I)

_POS = [re.compile(p, re.I) for p in POSITIVE_PATTERNS]
_NEG = [re.compile(p, re.I) for p in NEGATIVE_PATTERNS]


@dataclass
class Triage:
    decision: str  # skip | extract | ics
    score: int
    reasons: list[str] = field(default_factory=list)
    hints: dict = field(default_factory=dict)


def triage(mail: ParsedEmail, settings: Settings) -> Triage:
    score = 0
    reasons: list[str] = []
    labels = {label.upper() for label in mail.labels}
    user = settings.user_email_lower
    trusted = settings.trusted_domain_list

    def add(points: int, why: str) -> None:
        nonlocal score
        score += points
        reasons.append(f"{points:+d} {why}")

    # Gmail already sorted this mail. Trust it.
    gmail_category = next((l for l in labels if l.startswith("CATEGORY_")), None)
    if "CATEGORY_PROMOTIONS" in labels:
        add(-4, "gmail category promotions")
    if "CATEGORY_SOCIAL" in labels:
        add(-4, "gmail category social")
    if "CATEGORY_FORUMS" in labels:
        add(-1, "gmail category forums")
    if "CATEGORY_PERSONAL" in labels:
        add(+2, "gmail category personal")
    if "IMPORTANT" in labels:
        add(+1, "gmail marked important")
    if "STARRED" in labels:
        add(+2, "starred")
    if "SPAM" in labels or "TRASH" in labels:
        add(-10, "spam or trash")

    # Bulk-mail headers.
    if mail.list_unsubscribe:
        add(-1, "list-unsubscribe header")
    if mail.list_id:
        add(-1, "list-id header")
    if mail.precedence and mail.precedence.lower() in ("bulk", "list", "junk"):
        add(-1, f"precedence {mail.precedence.lower()}")
    if mail.auto_submitted and mail.auto_submitted.lower() != "no":
        add(-1, "auto-submitted")

    # Sender.
    trusted_sender = any(_domain_matches(mail.from_domain, d) for d in trusted)
    self_sent = bool(user) and mail.from_email == user
    if trusted_sender:
        add(+3, f"trusted sender domain {mail.from_domain}")
    if self_sent:
        add(+3, "sent by the user")
    if NOREPLY.match(mail.from_email):
        add(-1, "no-reply sender")

    # Recipients.
    direct_to_me = bool(user) and user in mail.recipients and len(mail.recipients) <= 3
    if direct_to_me:
        add(+1, "addressed directly to the user")
    elif not mail.recipients or any(UNDISCLOSED.search(a) for a in mail.to):
        add(-1, "no visible recipients")
    elif user and user not in mail.recipients:
        add(-1, "user not a direct recipient")

    # Calendar attachment.
    ics_method: str | None = None
    if mail.has_ics and mail.ics_text:
        events = parse_ics(mail.ics_text, settings.tz)
        if events:
            ics_method = (events[0].method or "").upper() or None
            add(+3, f"calendar attachment ({ics_method or 'no method'})")

    # Content.
    subject_pos = _count(_POS, mail.subject)
    subject_neg = _count(_NEG, mail.subject)
    body_head = mail.body_text[:3000]
    body_pos = _count(_POS, body_head)
    body_neg = _count(_NEG, body_head)
    if subject_pos:
        add(min(subject_pos, 2), f"{subject_pos} commitment word(s) in subject")
    if subject_neg:
        add(-min(subject_neg, 2), f"{subject_neg} marketing word(s) in subject")
    if body_pos:
        add(min(body_pos, 2), f"{body_pos} commitment word(s) in body")
    if body_neg:
        add(-min(body_neg, 2), f"{body_neg} marketing word(s) in body")
    if len(mail.body_text) > 15_000 and mail.body_text.count("http") > 25:
        add(-1, "long body with many links")

    hints = {
        "trusted_sender": trusted_sender,
        "self_sent": self_sent,
        "direct_to_me": direct_to_me,
        "bulk": mail.list_unsubscribe or "CATEGORY_PROMOTIONS" in labels or bool(mail.list_id),
        "personal_category": "CATEGORY_PERSONAL" in labels,
        "gmail_category": gmail_category,
        "ics_method": ics_method,
    }

    if ics_method is not None:
        decision = "ics"
    elif not mail.body_text.strip():
        decision = "skip"
        reasons.append("empty body")
    elif score <= SKIP_AT_OR_BELOW:
        decision = "skip"
    else:
        decision = "extract"
    return Triage(decision=decision, score=score, reasons=reasons, hints=hints)


def _count(patterns: list[re.Pattern], text: str) -> int:
    return sum(1 for p in patterns if p.search(text))


def _domain_matches(domain: str, trusted: str) -> bool:
    domain, trusted = domain.lower(), trusted.lower().lstrip("@")
    return domain == trusted or domain.endswith("." + trusted)
