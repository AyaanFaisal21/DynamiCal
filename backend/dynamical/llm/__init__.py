"""Model backends. Pick one with LLM_PROVIDER in .env."""

from __future__ import annotations

from ..config import Settings
from .base import ChatResult, ChatTurn, LLMBackend, LLMError, ToolSpec


def get_backend(settings: Settings) -> LLMBackend | None:
    """Return the configured backend, or None when no model is available."""
    provider = settings.llm_provider.lower()
    if provider == "gemini":
        if not settings.gemini_api_key:
            return None
        from .gemini import GeminiBackend

        return GeminiBackend(api_key=settings.gemini_api_key, model=settings.gemini_model)
    if provider == "local":
        from .local import LocalOpenAIBackend

        return LocalOpenAIBackend(
            base_url=settings.local_llm_base_url,
            model=settings.local_llm_model,
            api_key=settings.local_llm_api_key,
        )
    return None


__all__ = ["ChatResult", "ChatTurn", "LLMBackend", "LLMError", "ToolSpec", "get_backend"]
