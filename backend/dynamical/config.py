"""Application settings.

Values come from environment variables or a `.env` file at the repo root.
Relative paths resolve against the repo root, not the working directory.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Model. "gemini" needs GEMINI_API_KEY. "local" talks to an OpenAI-compatible
    # server such as Ollama, llama.cpp, or mlx-lm. "none" disables model calls.
    llm_provider: str = "gemini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    local_llm_base_url: str = "http://localhost:11434/v1"
    local_llm_model: str = "qwen2.5:7b-instruct"
    local_llm_api_key: str = "ollama"

    # Who the user is. The triage and policy stages use this.
    user_email: str | None = None
    user_profile: str = ""
    trusted_domains: str = ""

    timezone: str = Field(default="America/New_York", validation_alias="DYNAMICAL_TIMEZONE")
    db_path: Path = Field(default=ROOT / "data" / "dynamical.db", validation_alias="DYNAMICAL_DB")

    # Gmail
    gmail_credentials: Path = ROOT / "secrets" / "credentials.json"
    gmail_token: Path = ROOT / "secrets" / "token.json"
    gmail_query: str = "newer_than:30d -in:spam -in:trash -category:promotions -category:social"
    gmail_max_messages: int = 200

    # Behaviour
    sync_interval_minutes: int = 0
    day_start_hour: int = 8
    day_end_hour: int = 23
    auto_add_threshold: float = 0.75
    propose_threshold: float = 0.4

    # Server
    host: str = Field(default="127.0.0.1", validation_alias="DYNAMICAL_HOST")
    port: int = Field(default=8000, validation_alias="DYNAMICAL_PORT")

    @field_validator("db_path", "gmail_credentials", "gmail_token", mode="after")
    @classmethod
    def _make_absolute(cls, value: Path) -> Path:
        return value if value.is_absolute() else (ROOT / value).resolve()

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def trusted_domain_list(self) -> list[str]:
        return [d.strip().lower() for d in self.trusted_domains.split(",") if d.strip()]

    @property
    def user_email_lower(self) -> str | None:
        return self.user_email.lower() if self.user_email else None

    @property
    def llm_enabled(self) -> bool:
        provider = self.llm_provider.lower()
        if provider == "gemini":
            return bool(self.gemini_api_key)
        return provider == "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
