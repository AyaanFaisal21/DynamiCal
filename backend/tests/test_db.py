from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from dynamical.models import Event


def test_utc_datetime_roundtrip(db):
    start_local = datetime(2026, 10, 23, 18, 0, tzinfo=ZoneInfo("America/New_York"))
    with db.session() as s:
        s.add(Event(title="x", start=start_local, tz="America/New_York"))
    with db.session() as s:
        ev = s.scalars(select(Event)).one()
        assert ev.start.tzinfo is not None
        assert ev.start == datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc)
        assert ev.start == start_local


def test_naive_datetime_is_rejected(db):
    with pytest.raises(Exception):
        with db.session() as s:
            s.add(Event(title="x", start=datetime(2026, 1, 1, 12, 0), tz="UTC"))
