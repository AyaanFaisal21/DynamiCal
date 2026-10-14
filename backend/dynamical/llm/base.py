"""The small interface every backend implements.

Two operations cover the whole app:
  structured  one prompt in, one validated Pydantic object out
  chat        a conversation with tools, run to a final text answer
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

RESULT_LIMIT = 12_000


class LLMError(RuntimeError):
    pass


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the arguments
    fn: Callable[..., Any]


@dataclass
class ChatTurn:
    role: str  # user | assistant
    content: str


@dataclass
class ToolCallRecord:
    name: str
    args: dict[str, Any]
    result_preview: str


@dataclass
class ChatResult:
    text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


class LLMBackend(Protocol):
    name: str

    def structured(self, *, system: str, prompt: str, schema: type[T]) -> T: ...

    def chat(
        self,
        *,
        system: str,
        history: list[ChatTurn],
        tools: list[ToolSpec],
        max_rounds: int = 6,
    ) -> ChatResult: ...


# -- helpers shared by backends ----------------------------------------------------

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I | re.M)


def parse_json_text(text: str) -> Any:
    """Parse JSON from model output, tolerating code fences and leading prose."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Find the first balanced object or array.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"model did not return JSON: {text[:200]!r}")


def parse_into(schema: type[T], text: str) -> T:
    data = parse_json_text(text)
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise LLMError(f"model JSON did not match {schema.__name__}: {exc}") from exc


def run_tool(tools: list[ToolSpec], name: str, args: dict[str, Any]) -> str:
    """Execute a tool by name and return a JSON string for the model."""
    spec = next((t for t in tools if t.name == name), None)
    if spec is None:
        return json.dumps({"error": f"unknown tool {name}"})
    try:
        result = spec.fn(**args)
    except TypeError as exc:
        return json.dumps({"error": f"bad arguments for {name}: {exc}"})
    except Exception as exc:  # the model should see tool failures, not crash the chat
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
    text = json.dumps(result, default=str, ensure_ascii=False)
    if len(text) > RESULT_LIMIT:
        text = text[:RESULT_LIMIT] + '..."(truncated)'
    return text


def preview(text: str, limit: int = 160) -> str:
    return text if len(text) <= limit else text[:limit] + "..."
