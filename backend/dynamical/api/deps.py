from __future__ import annotations

from typing import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.db.new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_settings_dep(request: Request):
    return request.app.state.settings


def get_db(request: Request):
    return request.app.state.db


def get_backend_dep(request: Request):
    return request.app.state.backend
