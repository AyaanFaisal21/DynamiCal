from __future__ import annotations

from pathlib import Path

import pytest

from dynamical.config import Settings
from dynamical.db import Database
from dynamical.gmail.parse import ParsedEmail, parse_eml_file

FIXTURES = Path(__file__).parent / "fixtures" / "emails"

from dynamical.demo import LABELS  # noqa: E402


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        user_email="sam@scarlet.example.edu",
        user_profile="Undergraduate CS student.",
        trusted_domains="example.edu",
        timezone="America/New_York",
        llm_provider="none",
    )


@pytest.fixture
def db() -> Database:
    database = Database.in_memory()
    database.create_all()
    return database


def load_fixture(name: str) -> ParsedEmail:
    mail = parse_eml_file(FIXTURES / f"{name}.eml", labels=LABELS[name])
    mail.thread_id = f"thread-{name}"
    return mail


@pytest.fixture
def load():
    return load_fixture
