from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dynamical.ingest.ics import parse_ics

NY = ZoneInfo("America/New_York")


def test_google_invite(load):
    mail = load("04_gcal_invite")
    events = parse_ics(mail.ics_text, NY)
    assert len(events) == 1
    ev = events[0]
    assert ev.summary == "CS 419 Project Sync"
    assert ev.start == datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)
    assert ev.end == datetime(2026, 10, 15, 21, 0, tzinfo=timezone.utc)
    assert ev.method == "REQUEST"
    assert ev.location == "CoRE 305"
    assert "sam@scarlet.example.edu" in ev.attendees
    assert ev.organizer == "jordan.lee@cs.example.edu"
    assert ev.uid == "cs419sync20261015@google.com"
    assert ev.cancelled is False


def test_all_day_and_floating_times():
    text = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:a
SUMMARY:Reading day
DTSTART;VALUE=DATE:20261120
END:VEVENT
BEGIN:VEVENT
UID:b
SUMMARY:Floating
DTSTART:20261120T090000
DURATION:PT2H
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR"""
    events = {e.uid: e for e in parse_ics(text, NY)}
    reading = events["a"]
    assert reading.all_day is True
    assert reading.start == datetime(2026, 11, 20, 5, 0, tzinfo=timezone.utc)  # EST midnight
    assert reading.end == datetime(2026, 11, 21, 5, 0, tzinfo=timezone.utc)
    floating = events["b"]
    assert floating.start == datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
    assert floating.end == datetime(2026, 11, 20, 16, 0, tzinfo=timezone.utc)
    assert floating.cancelled is True


def test_garbage_is_empty():
    assert parse_ics("not a calendar", NY) == []
