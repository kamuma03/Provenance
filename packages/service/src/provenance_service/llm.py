"""LLM client abstraction + task-based provider routing (A2).

Agents and the extraction engine take an optional LLMClient. With none, they run on
deterministic heuristics (offline-safe); with a client they get richer behaviour. Routing
is per task via env `LLM_<TASK>` (e.g. LLM_CRITIC) — mix Claude (Anthropic) with local
open-source models served over an OpenAI-compatible API (vLLM / Ollama / SGLang).

Spec grammar: "<provider>:<model>" — provider ∈ anthropic | local | openai | vllm |
ollama. Empty / "heuristic" / "none" ⇒ no client (heuristic mode). A provider that isn't
actually available (no API key, no base URL) resolves to None, so the system degrades to
heuristics rather than erroring.

Tier aliases: a spec of "high" or "low" expands to LLM_TIER_HIGH / LLM_TIER_LOW, so you
define the two models (e.g. a capable 27B and a fast 9B local pair, or Claude tiers) once
and route each task to a tier — swapping the underlying model is then a one-line change.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger("llm")


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
        max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "2048"))  # was hardcoded 1024 (M-14)
        msg = await self._client.messages.create(
            model=self.model_id,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        if getattr(msg, "stop_reason", None) == "max_tokens":
            # A truncated answer must not be treated as complete downstream (review M-14).
            log.warning("Anthropic response truncated at max_tokens=%d (model=%s)",
                        max_tokens, self.model_id)
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
        payload: dict[str, object] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "2048")),
            "temperature": 0,
        }
        # Reasoning ("thinking") models otherwise spend the whole token budget in a hidden
        # reasoning trace and return empty content (finish_reason=length). reasoning_effort is
        # the OpenAI-standard control; Ollama/vLLM/SGLang honor it. "none" ⇒ direct answer,
        # which is what the extraction/detection/planner/synth tasks want. Configurable.
        effort = os.environ.get("LLM_REASONING_EFFORT", "none").strip()
        if effort:
            payload["reasoning_effort"] = effort
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            log.warning("local LLM response truncated (finish_reason=length, model=%s)",
                        self.model_id)
        # Reasoning models can return null content; return "" rather than the literal "None"
        # that str(None) would produce and poison the answer text (review M-14).
        return choice.get("message", {}).get("content") or ""


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
_TIER_ENV = {"high": "LLM_TIER_HIGH", "low": "LLM_TIER_LOW"}

# Clients are reused across requests, keyed on their connection identity (provider, model,
# base_url) — so the crew doesn't build a fresh Anthropic SDK client / httpx pool every call
# (review M-14). The cache is only populated *after* the availability check (key / base_url),
# so a spec that resolves to None (heuristic) is never cached and env changes that flip a
# provider on/off are still honored.
_CLIENT_CACHE: dict[tuple[str, str, str], LLMClient] = {}


def _cached(
    provider: str, model: str, base_url: str, factory: Callable[[], LLMClient]
) -> LLMClient:
    key = (provider, model, base_url)
    client = _CLIENT_CACHE.get(key)
    if client is None:
        client = factory()
        _CLIENT_CACHE[key] = client
    return client


def client_from_spec(spec: str) -> LLMClient | None:
    """Resolve a "<provider>:<model>" spec to a client, or None if unavailable/heuristic.

    A "high"/"low" tier alias expands to LLM_TIER_HIGH / LLM_TIER_LOW (one level — an
    alias that points at another alias resolves to heuristic, never loops).
    """
    spec = (spec or "").strip()
    if spec.lower() in _TIER_ENV:
        spec = os.environ.get(_TIER_ENV[spec.lower()], "").strip()
    if not spec or spec.lower() in ("heuristic", "none", "off", "high", "low"):
        return None
    provider, _, model = spec.partition(":")
    provider = provider.lower()

    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None  # no key → heuristic fallback
        try:
            return _cached("anthropic", model, "", lambda: AnthropicLLMClient(model or None))
        except Exception:  # pragma: no cover - SDK missing
            return None
    if provider in _LOCAL_PROVIDERS:
        base_url = os.environ.get("LLM_LOCAL_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
        if not base_url:
            return None  # no local endpoint configured → heuristic fallback
        api_key = os.environ.get("LLM_LOCAL_API_KEY")
        return _cached(
            "local", model, base_url,
            lambda: OpenAICompatLLMClient(base_url, model or "default", api_key),
        )
    raise ValueError(f"unknown LLM provider in spec: {spec!r}")


def validate_routes(tasks: list[str] | None = None) -> None:
    """Fail fast at startup on an unknown-provider typo in any configured route, instead of
    raising per-request deep in a handler (review M-14). Missing keys/endpoints are NOT errors
    — those are the intended heuristic fallback — so this only rejects malformed provider names.
    """
    specs: list[str] = []
    for task in tasks or list(DEFAULT_ROUTES):
        spec = os.environ.get(f"LLM_{task.upper()}") or DEFAULT_ROUTES.get(task, "")
        if spec:
            specs.append(spec)
    for env_key in ("LLM_TIER_HIGH", "LLM_TIER_LOW", "LLM_DEFAULT"):
        if os.environ.get(env_key):
            specs.append(os.environ[env_key])
    for spec in specs:
        s = spec.strip()
        if not s or s.lower() in ("heuristic", "none", "off", "high", "low"):
            continue
        provider = s.partition(":")[0].lower()
        if provider != "anthropic" and provider not in _LOCAL_PROVIDERS:
            raise ValueError(f"unknown LLM provider in configured route: {spec!r}")


def get_llm(task: str | None = None) -> LLMClient | None:
    """Resolve the LLM client for a task. Env `LLM_<TASK>` overrides the default route."""
    if task is not None:
        spec = os.environ.get(f"LLM_{task.upper()}")
        if spec is None:
            spec = DEFAULT_ROUTES.get(task, os.environ.get("LLM_DEFAULT", ""))
    else:
        spec = os.environ.get("LLM_DEFAULT", "anthropic:claude-opus-4-8")
    return client_from_spec(spec)
