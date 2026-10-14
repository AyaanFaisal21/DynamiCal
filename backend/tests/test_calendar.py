from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dynamical.calendar.conflicts import find_conflicts
from dynamical.calendar.freetime import free_slots, suggest_blocks
from dynamical.models import Event

NY = ZoneInfo("America/New_York")


def ev(id, h, m=0, dur=60, day=date(2026, 10, 15), **kw):
    start = datetime(day.year, day.month, day.day, h, m, tzinfo=NY).astimezone(timezone.utc)
    fields = dict(id=id, title=f"e{id}", start=start, end=start + timedelta(minutes=dur), tz="America/New_York", status="confirmed", kind="event", tentative=False, all_day=False)
    fields.update(kw)
    return Event(**fields)


def test_conflicts():
    events = [ev(1, 9), ev(2, 9, 30), ev(3, 11), ev(4, 11, 15, tentative=True), ev(5, 14, kind="deadline", dur=0), ev(6, 14)]
    found = find_conflicts(events)
    pairs = {(c.a.id, c.b.id): c for c in found}
    assert set(pairs) == {(1, 2), (3, 4)}
    assert pairs[(1, 2)].severity == "hard" and pairs[(1, 2)].overlap_minutes == 30
    assert pairs[(3, 4)].severity == "soft"


def test_free_slots_basic():
    events = [ev(1, 9, dur=120), ev(2, 13, dur=60), ev(3, 13, 30, dur=90)]
    slots = free_slots(events, date(2026, 10, 15), NY, day_start_hour=8, day_end_hour=18, min_minutes=30)
    local = [(s.start.astimezone(NY).hour, s.end.astimezone(NY).hour) for s in slots]
    assert local == [(8, 9), (11, 13), (15, 18)]


def test_free_slots_ignore_proposed_deadlines_and_allday():
    events = [ev(1, 10, status="proposed"), ev(2, 12, kind="deadline", dur=0), ev(3, 0, dur=1440, all_day=True)]
    slots = free_slots(events, date(2026, 10, 15), NY, day_start_hour=8, day_end_hour=18)
    assert len(slots) == 1 and slots[0].minutes == 600


def test_suggest_blocks_works_backwards_from_target():
    exam = ev(1, 20, 40, dur=80, day=date(2026, 10, 28), kind="exam")
    busy = [ev(2, 8, dur=900, day=date(2026, 10, 27))]  # the day before is full, 8 AM to 11 PM
    now = datetime(2026, 10, 25, 9, 0, tzinfo=NY).astimezone(timezone.utc)
    blocks = suggest_blocks(
        [exam] + busy,
        target_start=exam.start,
        total_minutes=270,
        tz=NY,
        day_start_hour=8,
        day_end_hour=23,
        now=now,
    )
    days = [b.day for b in blocks]
    assert date(2026, 10, 27) not in days
    assert sum(b.minutes for b in blocks) == 270
    assert all(b.end <= exam.start for b in blocks)
    assert days == sorted(days)
