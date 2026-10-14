"""A model stand-in for tests. Returns canned extractions keyed by subject text."""

from __future__ import annotations

from dynamical.ingest.extract import Extraction
from dynamical.llm.base import ChatResult, ChatTurn, ToolSpec, run_tool


class FakeBackend:
    name = "fake"
    model = "fake-1"

    def __init__(self, canned: dict[str, Extraction], chat_plan: list[tuple[str, dict]] | None = None):
        self.canned = canned
        self.calls: list[str] = []
        self.chat_plan = chat_plan or []

    def structured(self, *, system: str, prompt: str, schema):
        self.calls.append(prompt)
        for needle, extraction in self.canned.items():
            if needle in prompt:
                return extraction
        return Extraction(relationship="none", summary="nothing", rationale="no match", events=[], tasks=[])

    def chat(self, *, system: str, history: list[ChatTurn], tools: list[ToolSpec], max_rounds: int = 6) -> ChatResult:
        outputs = [run_tool(tools, name, args) for name, args in self.chat_plan]
        return ChatResult(text="\n".join(outputs) or "ok")
