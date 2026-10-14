from datetime import datetime, timezone

from dynamical.gmail.parse import html_to_text


def test_plain_text_fields(load):
    mail = load("01_eventbrite_confirmation")
    assert mail.from_email == "orders@eventbrite.com"
    assert mail.from_name == "Eventbrite"
    assert mail.subject.startswith("Your ticket for")
    assert mail.to == ["sam@scarlet.example.edu"]
    assert mail.list_unsubscribe is True
    assert mail.date == datetime(2026, 10, 13, 18, 2, 11, tzinfo=timezone.utc)
    assert "Busch Student Center" in mail.body_text
    assert mail.has_ics is False
    assert mail.message_id == "order-1234567890@eventbrite.com"


def test_html_body_becomes_text(load):
    mail = load("02_newsletter_promo")
    assert "<" not in mail.body_text
    assert "Salsa night" in mail.body_text
    assert "color:red" not in mail.body_text
    assert mail.precedence == "bulk"


def test_calendar_part_is_detected(load):
    mail = load("04_gcal_invite")
    assert mail.has_ics is True
    assert "BEGIN:VEVENT" in (mail.ics_text or "")
    assert "invited to the following event" in mail.body_text


def test_list_headers(load):
    mail = load("05_course_exam")
    assert mail.list_id is not None
    assert mail.from_domain == "cs.example.edu"


def test_html_to_text_keeps_link_targets():
    text = html_to_text('<p>Get your <a href="https://t.example/abc">ticket</a> now<br>Thanks</p>')
    assert "ticket (https://t.example/abc)" in text
    assert text.splitlines()[-1] == "Thanks"
    assert "now" in text
