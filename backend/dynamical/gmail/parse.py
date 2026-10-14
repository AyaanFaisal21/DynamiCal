"""Turn an RFC 822 message into the fields the pipeline needs.

Gmail gives us the raw message with `format=raw`, and test fixtures are `.eml`
files, so one parser serves both.
"""

from __future__ import annotations

import email
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

from bs4 import BeautifulSoup

BODY_LIMIT = 40_000
SNIPPET_LIMIT = 200


@dataclass
class ParsedEmail:
    message_id: str
    thread_id: str | None
    subject: str
    from_name: str
    from_email: str
    to: list[str]
    cc: list[str]
    date: datetime  # aware, UTC
    body_text: str
    snippet: str
    list_unsubscribe: bool
    list_id: str | None
    precedence: str | None
    auto_submitted: str | None
    has_ics: bool
    ics_text: str | None
    attachments: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)

    @property
    def from_domain(self) -> str:
        return self.from_email.rsplit("@", 1)[-1].lower() if "@" in self.from_email else ""

    @property
    def recipients(self) -> list[str]:
        return [a.lower() for a in self.to + self.cc]


def parse_rfc822(
    raw: bytes,
    *,
    message_id: str | None = None,
    thread_id: str | None = None,
    labels: list[str] | tuple[str, ...] = (),
) -> ParsedEmail:
    msg: EmailMessage = email.message_from_bytes(raw, policy=policy.default)  # type: ignore[assignment]

    subject = _header(msg, "Subject")
    from_name, from_email = _first_address(msg.get_all("From", []))
    to = _addresses(msg.get_all("To", []))
    cc = _addresses(msg.get_all("Cc", []))
    body_text, ics_text, attachments = _walk_parts(msg)
    body_text = body_text[:BODY_LIMIT]

    rfc_id = _header(msg, "Message-ID").strip("<> ")
    mid = message_id or rfc_id or hashlib.sha1(raw).hexdigest()

    return ParsedEmail(
        message_id=mid,
        thread_id=thread_id,
        subject=subject,
        from_name=from_name,
        from_email=from_email.lower(),
        to=to,
        cc=cc,
        date=_parse_date(msg),
        body_text=body_text,
        snippet=_snippet(body_text),
        list_unsubscribe=bool(_header(msg, "List-Unsubscribe")),
        list_id=_header(msg, "List-Id") or None,
        precedence=(_header(msg, "Precedence") or None),
        auto_submitted=(_header(msg, "Auto-Submitted") or None),
        has_ics=ics_text is not None,
        ics_text=ics_text,
        attachments=attachments,
        labels=list(labels),
    )


def parse_eml_file(path: Path, labels: list[str] | tuple[str, ...] = ()) -> ParsedEmail:
    raw = path.read_bytes()
    parsed = parse_rfc822(raw, labels=labels)
    # Fixtures without a Message-ID still need a stable id across runs.
    if not _header_from_bytes(raw, "Message-ID"):
        parsed.message_id = "eml-" + hashlib.sha1(raw).hexdigest()[:24]
    return parsed


# -- internals -----------------------------------------------------------------


def _header(msg: EmailMessage, name: str) -> str:
    value = msg.get(name)
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:  # malformed header objects
        return ""


def _header_from_bytes(raw: bytes, name: str) -> str:
    m = re.search(rf"^{name}:\s*(.+)$", raw.decode("utf-8", "replace"), re.I | re.M)
    return m.group(1).strip() if m else ""


def _addresses(values) -> list[str]:
    pairs = getaddresses([str(v) for v in values])
    return [addr.lower() for _name, addr in pairs if addr]


def _first_address(values) -> tuple[str, str]:
    pairs = [(n, a) for n, a in getaddresses([str(v) for v in values]) if a]
    if not pairs:
        return "", ""
    name, addr = pairs[0]
    return name.strip().strip('"'), addr


def _parse_date(msg: EmailMessage) -> datetime:
    header = msg.get("Date")
    dt: datetime | None = None
    if header is not None:
        dt = getattr(header, "datetime", None)
        if dt is None:
            try:
                dt = parsedate_to_datetime(str(header))
            except (TypeError, ValueError):
                dt = None
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _decode_part(part: EmailMessage) -> str:
    try:
        content = part.get_content()
        if isinstance(content, bytes):
            return content.decode(part.get_content_charset() or "utf-8", "replace")
        return str(content)
    except Exception:
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            return payload.decode(part.get_content_charset() or "utf-8", "replace")
        return ""


def _walk_parts(msg: EmailMessage) -> tuple[str, str | None, list[str]]:
    plain: list[str] = []
    html: list[str] = []
    ics: str | None = None
    attachments: list[str] = []

    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        filename = part.get_filename() or ""
        disposition = (part.get_content_disposition() or "").lower()

        if ctype == "text/calendar" or filename.lower().endswith(".ics") or ctype == "application/ics":
            if ics is None:
                ics = _decode_part(part)
            if filename:
                attachments.append(filename)
            continue
        if disposition == "attachment" or filename:
            attachments.append(filename or ctype)
            continue
        if ctype == "text/plain":
            plain.append(_decode_part(part))
        elif ctype == "text/html":
            html.append(_decode_part(part))

    text = "\n".join(p for p in plain if p.strip())
    if not text.strip() and html:
        text = html_to_text("\n".join(html))
    return _normalise(text), ics, attachments


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head", "title", "meta", "noscript"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    # Keep link targets for tickets and calendar links. Marketing mail has many; it is fine.
    for a in soup.find_all("a"):
        href = a.get("href")
        label = a.get_text(" ", strip=True)
        if href and label and href.startswith("http") and label.lower() not in href.lower():
            a.replace_with(f"{label} ({href})")
    return _normalise(soup.get_text("\n"))


def _normalise(text: str) -> str:
    text = text.replace("\xa0", " ").replace("​", "").replace("\r\n", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _snippet(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed[:SNIPPET_LIMIT]
