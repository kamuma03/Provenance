"""LLM client abstraction (A2).

The crew's Planner/Critic/Synthesizer take an optional LLMClient. Offline, they run on
deterministic heuristics; with a client (Claude on the Spark) they get richer behaviour.
A MockLLMClient drives LLM-path tests; the Anthropic client is lazy-loaded.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Protocol


class LLMClient(Protocol):
    async def complete(self, system: str, prompt: str) -> str: ...


class MockLLMClient:
    """Scripted responses for tests: a list (consumed in order) or a callable."""

    model_id = "mock-llm"

    def __init__(self, responses: list[str] | Callable[[str, str], str]) -> None:
        self._responses = responses
        self._i = 0

    async def complete(self, system: str, prompt: str) -> str:
        if callable(self._responses):
            return self._responses(system, prompt)
        if self._i < len(self._responses):
            out = self._responses[self._i]
            self._i += 1
            return out
        return ""


class AnthropicLLMClient:
    """Real Claude client (lazy import). Used on the Spark / with a configured endpoint."""

    def __init__(self, model: str | None = None) -> None:
        import anthropic

        self._client = anthropic.AsyncAnthropic()
        self.model_id = model or os.environ.get("LLM_MODEL", "claude-opus-4-8")

    async def complete(self, system: str, prompt: str) -> str:
        msg = await self._client.messages.create(
            model=self.model_id,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in msg.content if block.type == "text")


def get_llm() -> LLMClient | None:
    """Real Claude client when an API key is configured; otherwise None (heuristic mode)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return AnthropicLLMClient()
        except Exception:  # pragma: no cover
            return None
    return None
