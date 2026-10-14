from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dynamical.dates import day_bounds, fmt_range, parse_datetime, week_bounds

NY = ZoneInfo("America/New_York")


def test_parse_iso_with_offset():
    assert parse_datetime("2026-10-23T18:00:00-04:00", NY) == datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc)


def test_parse_naive_uses_user_zone():
    assert parse_datetime("2026-10-23T18:00:00", NY) == datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc)


def test_parse_date_only_is_local_midnight():
    assert parse_datetime("2026-10-23", NY) == datetime(2026, 10, 23, 4, 0, tzinfo=timezone.utc)


def test_parse_junk():
    assert parse_datetime("sometime next week", NY) is None
    assert parse_datetime("", NY) is None


def test_day_bounds_across_dst_end():
    start, end = day_bounds(date(2026, 11, 1), NY)
    assert start == datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)
    assert end - start == timedelta(hours=25)


def test_week_bounds_start_monday():
    start, end = week_bounds(date(2026, 10, 15), NY)  # a Thursday
    assert start == datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)
    assert end - start == timedelta(days=7)


def test_fmt_range_same_day():
    s = datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc)
    e = datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)
    assert fmt_range(s, e, NY) == "Fri Oct 23, 2026 6:00 PM to 9:00 PM"
