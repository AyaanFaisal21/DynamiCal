"""SQLAlchemy engine, session factory, and the UTC datetime column type."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator[datetime]):
    """Store aware datetimes as UTC.

    SQLite has no timezone type and returns naive values. Without this wrapper
    a stored 3 PM EDT would come back as a naive 7 PM and be shown as 7 PM.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTCDateTime columns require timezone-aware datetimes")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _apply_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # pragma: no cover - trivial
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


class Database:
    def __init__(self, engine: Engine):
        self.engine = engine
        self._factory = sessionmaker(bind=engine, expire_on_commit=False)

    @classmethod
    def from_path(cls, path: Path) -> "Database":
        path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        _apply_pragmas(engine)
        return cls(engine)

    @classmethod
    def in_memory(cls) -> "Database":
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        _apply_pragmas(engine)
        return cls(engine)

    def create_all(self) -> None:
        from . import models  # noqa: F401  (registers the tables)

        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A unit of work. Commits on success, rolls back on error."""
        s = self._factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def new_session(self) -> Session:
        """A session the caller manages. Used by the API dependency."""
        return self._factory()
