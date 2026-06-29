"""LLM client abstraction + task-based provider routing (A2).

Agents and the extraction engine take an optional LLMClient. With none, they run on
deterministic heuristics (offline-safe); with a client they get richer behaviour. Routing
is per task via env `LLM_<TASK>` (e.g. LLM_CRITIC) — mix Claude (Anthropic) with local
open-source models served over an OpenAI-compatible API (vLLM / Ollama / SGLang).

Spec grammar: "<provider>:<model>" — provider ∈ anthropic | local | openai | vllm |
ollama. Empty / "heuristic" / "none" ⇒ no client (heuristic mode). A provider that isn't
actually available (no API key, no base URL) resolves to None, so the system degrades to
heuristics rather than erroring.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Protocol


class LLMClient(Protocol):
    model_id: str

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
    """Real Claude client (lazy import). Used with a configured ANTHROPIC_API_KEY."""

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


class OpenAICompatLLMClient:
    """OpenAI-compatible chat client — covers vLLM, Ollama, and SGLang by base_url.

    One class, many local servers: point base_url at the server's `/v1` endpoint.
    """

    def __init__(self, base_url: str, model: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_id = model
        self._api_key = api_key

    async def complete(self, system: str, prompt: str) -> str:
        import httpx

        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 1024,
            "temperature": 0,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        return str(data["choices"][0]["message"]["content"])


# Recommended per-task defaults (volume × difficulty × where-it-runs). Each resolves to
# None when its provider isn't configured, so the default is heuristic until you wire it.
DEFAULT_ROUTES: dict[str, str] = {
    "extraction": "local:qwen3-14b",          # token sink → local, on the Spark
    "detection": "",                           # heuristic is enough
    "planner": "anthropic:claude-sonnet-4-6",  # light decomposition
    "synthesizer": "anthropic:claude-sonnet-4-6",  # fluent generation
    "critic": "anthropic:claude-opus-4-8",     # correctness-critical; judge ≥ generator
    "eval_judge": "anthropic:claude-opus-4-8",  # gold judge, ≠ the generator
}

_LOCAL_PROVIDERS = {"local", "openai", "vllm", "ollama", "sglang"}


def client_from_spec(spec: str) -> LLMClient | None:
    """Resolve a "<provider>:<model>" spec to a client, or None if unavailable/heuristic."""
    spec = (spec or "").strip()
    if not spec or spec in ("heuristic", "none", "off"):
        return None
    provider, _, model = spec.partition(":")
    provider = provider.lower()

    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None  # no key → heuristic fallback
        try:
            return AnthropicLLMClient(model or None)
        except Exception:  # pragma: no cover - SDK missing
            return None
    if provider in _LOCAL_PROVIDERS:
        base_url = os.environ.get("LLM_LOCAL_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
        if not base_url:
            return None  # no local endpoint configured → heuristic fallback
        api_key = os.environ.get("LLM_LOCAL_API_KEY")
        return OpenAICompatLLMClient(base_url, model or "default", api_key)
    raise ValueError(f"unknown LLM provider in spec: {spec!r}")


def get_llm(task: str | None = None) -> LLMClient | None:
    """Resolve the LLM client for a task. Env `LLM_<TASK>` overrides the default route."""
    if task is not None:
        spec = os.environ.get(f"LLM_{task.upper()}")
        if spec is None:
            spec = DEFAULT_ROUTES.get(task, os.environ.get("LLM_DEFAULT", ""))
    else:
        spec = os.environ.get("LLM_DEFAULT", "anthropic:claude-opus-4-8")
    return client_from_spec(spec)
