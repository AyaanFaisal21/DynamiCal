"""Local backend for any OpenAI-compatible server.

Works with Ollama (`ollama serve`, port 11434), llama.cpp (`llama-server`),
and mlx-lm (`mlx_lm.server`). Tool use goes through a JSON planner, so the
model only needs JSON mode, not native tool calling.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from .base import (
    ChatResult,
    ChatTurn,
    LLMError,
    ToolCallRecord,
    ToolSpec,
    parse_into,
    parse_json_text,
    preview,
    run_tool,
)

T = TypeVar("T", bound=BaseModel)

PLANNER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["tool", "answer"]},
        "tool": {"type": ["string", "null"]},
        "args": {"type": ["object", "null"]},
        "answer": {"type": ["string", "null"]},
    },
    "required": ["action"],
}


class LocalOpenAIBackend:
    name = "local"

    def __init__(self, base_url: str, model: str, api_key: str = "ollama", timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._client = httpx.Client(timeout=timeout)

    def structured(self, *, system: str, prompt: str, schema: type[T]) -> T:
        json_schema = schema.model_json_schema()
        messages = [
            {
                "role": "system",
                "content": system
                + "\n\nRespond with one JSON object only, matching this JSON schema:\n"
                + json.dumps(json_schema),
            },
            {"role": "user", "content": prompt},
        ]
        text = self._complete(messages, json_schema=json_schema, temperature=0.1)
        return parse_into(schema, text)

    def chat(
        self,
        *,
        system: str,
        history: list[ChatTurn],
        tools: list[ToolSpec],
        max_rounds: int = 6,
    ) -> ChatResult:
        tool_lines = "\n".join(
            f"- {t.name}: {t.description}\n  arguments JSON schema: {json.dumps(t.parameters)}" for t in tools
        )
        planner_system = (
            system
            + "\n\nYou may call tools to look things up before answering. Reply with exactly one JSON object.\n"
            + 'To call a tool: {"action": "tool", "tool": "<name>", "args": {...}}\n'
            + 'To answer the user: {"action": "answer", "answer": "<your reply in plain text>"}\n'
            + "Available tools:\n"
            + (tool_lines or "(none)")
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": planner_system}]
        messages += [{"role": t.role, "content": t.content} for t in history]
        log: list[ToolCallRecord] = []

        for _ in range(max_rounds):
            text = self._complete(messages, json_schema=PLANNER_SCHEMA, temperature=0.2)
            plan = self._plan(text)
            if plan.get("action") != "tool" or not plan.get("tool"):
                return ChatResult(text=str(plan.get("answer") or text).strip(), tool_calls=log)
            name = str(plan["tool"])
            args = plan.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            result = run_tool(tools, name, args)
            log.append(ToolCallRecord(name=name, args=args, result_preview=preview(result)))
            messages.append({"role": "assistant", "content": text})
            messages.append(
                {
                    "role": "user",
                    "content": f"Result of {name}:\n{result}\n\nCall another tool if needed, or answer now.",
                }
            )

        messages.append({"role": "user", "content": 'Answer now: {"action": "answer", "answer": "..."}'})
        text = self._complete(messages, json_schema=PLANNER_SCHEMA, temperature=0.2)
        plan = self._plan(text)
        return ChatResult(text=str(plan.get("answer") or text).strip(), tool_calls=log)

    # -- internals ---------------------------------------------------------------

    @staticmethod
    def _plan(text: str) -> dict[str, Any]:
        try:
            data = parse_json_text(text)
        except LLMError:
            return {"action": "answer", "answer": text}
        return data if isinstance(data, dict) else {"action": "answer", "answer": text}

    def _complete(self, messages: list[dict[str, str]], *, json_schema: dict | None, temperature: float) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        # Try strict schema mode, then plain JSON mode, then nothing.
        formats: list[dict[str, Any] | None] = []
        if json_schema is not None:
            formats.append(
                {
                    "type": "json_schema",
                    "json_schema": {"name": "response", "schema": json_schema, "strict": True},
                }
            )
            formats.append({"type": "json_object"})
        formats.append(None)

        last_error: Exception | None = None
        for fmt in formats:
            if fmt is None:
                body.pop("response_format", None)
            else:
                body["response_format"] = fmt
            try:
                response = self._client.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
            except httpx.HTTPError as exc:
                raise LLMError(
                    f"local model server unreachable at {self.base_url}: {exc}. Is it running?"
                ) from exc
            if response.status_code == 400 and fmt is not None:
                last_error = LLMError(response.text[:300])
                continue
            if response.status_code >= 400:
                raise LLMError(f"local model server returned {response.status_code}: {response.text[:300]}")
            data = response.json()
            try:
                return data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMError(f"unexpected response shape: {str(data)[:300]}") from exc
        raise LLMError(f"local model server rejected every request format: {last_error}")
