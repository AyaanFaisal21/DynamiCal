"""Gemini backend through the google-genai SDK.

Uses `models.generate_content`, which Google documents as fully supported next
to the newer Interactions API. Function calling is run by hand so every tool
call is logged and bounded.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from .base import ChatResult, ChatTurn, LLMError, ToolCallRecord, ToolSpec, parse_into, preview, run_tool

T = TypeVar("T", bound=BaseModel)


class GeminiBackend:
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        from google import genai

        self.model = model
        self._client = genai.Client(api_key=api_key)

    # Gemini 3 models accept a thinking level. Older models reject it.
    def _thinking(self, level: str):
        from google.genai import types

        if not self.model.startswith("gemini-3"):
            return None
        return types.ThinkingConfig(thinking_level=getattr(types.ThinkingLevel, level))

    def structured(self, *, system: str, prompt: str, schema: type[T]) -> T:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.1,
            thinking_config=self._thinking("LOW"),
        )
        try:
            response = self._client.models.generate_content(
                model=self.model, contents=prompt, config=config
            )
        except Exception as exc:
            raise LLMError(f"gemini request failed: {exc}") from exc
        return parse_into(schema, response.text or "")

    def chat(
        self,
        *,
        system: str,
        history: list[ChatTurn],
        tools: list[ToolSpec],
        max_rounds: int = 6,
    ) -> ChatResult:
        from google.genai import types

        declarations = [
            types.FunctionDeclaration(
                name=t.name, description=t.description, parameters_json_schema=t.parameters
            )
            for t in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.3,
            thinking_config=self._thinking("LOW"),
        )
        contents = [
            types.Content(
                role="user" if turn.role == "user" else "model",
                parts=[types.Part.from_text(text=turn.content)],
            )
            for turn in history
        ]
        log: list[ToolCallRecord] = []

        for _ in range(max_rounds):
            response = self._generate(contents, config)
            calls = response.function_calls or []
            if not calls:
                return ChatResult(text=response.text or "", tool_calls=log)
            contents.append(response.candidates[0].content)
            result_parts = []
            for call in calls:
                args = dict(call.args or {})
                result = run_tool(tools, call.name or "", args)
                log.append(ToolCallRecord(name=call.name or "", args=args, result_preview=preview(result)))
                result_parts.append(
                    types.Part.from_function_response(name=call.name or "", response={"result": result})
                )
            contents.append(types.Content(role="user", parts=result_parts))

        # Out of rounds: ask for a plain answer with the tools switched off.
        final_config = types.GenerateContentConfig(
            system_instruction=system, temperature=0.3, thinking_config=self._thinking("LOW")
        )
        contents.append(
            types.Content(role="user", parts=[types.Part.from_text(text="Answer now with what you have.")])
        )
        response = self._generate(contents, final_config)
        return ChatResult(text=response.text or "", tool_calls=log)

    def _generate(self, contents, config):
        try:
            return self._client.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except Exception as exc:
            raise LLMError(f"gemini request failed: {exc}") from exc
