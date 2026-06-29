"""LLM router + OpenAI-compat client tests (A2)."""

from __future__ import annotations

import httpx
import pytest
from provenance_service.llm import (
    AnthropicLLMClient,
    OpenAICompatLLMClient,
    client_from_spec,
    get_llm,
)


def test_empty_and_heuristic_specs_resolve_to_none() -> None:
    assert client_from_spec("") is None
    assert client_from_spec("heuristic") is None
    assert client_from_spec("none") is None


def test_anthropic_spec_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client_from_spec("anthropic:claude-opus-4-8") is None  # no key → heuristic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    client = client_from_spec("anthropic:claude-opus-4-8")
    assert isinstance(client, AnthropicLLMClient)
    assert client.model_id == "claude-opus-4-8"


def test_local_spec_needs_a_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_LOCAL_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    assert client_from_spec("local:qwen3-14b") is None  # no endpoint → heuristic

    monkeypatch.setenv("LLM_LOCAL_BASE_URL", "http://spark:8000/v1")
    client = client_from_spec("vllm:qwen3-14b")
    assert isinstance(client, OpenAICompatLLMClient)
    assert client.base_url == "http://spark:8000/v1"
    assert client.model_id == "qwen3-14b"


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError):
        client_from_spec("cohere:command")


def test_router_reads_per_task_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_CRITIC", "anthropic:claude-sonnet-4-6")  # override the Opus default
    client = get_llm("critic")
    assert isinstance(client, AnthropicLLMClient)
    assert client.model_id == "claude-sonnet-4-6"


def test_router_defaults_to_heuristic_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_LOCAL_BASE_URL", raising=False)
    # No provider available → every task falls back to heuristic (None).
    assert get_llm("critic") is None
    assert get_llm("extraction") is None
    assert get_llm("detection") is None


@pytest.mark.asyncio
async def test_openai_compat_posts_chat_completions(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None: ...
        def json(self) -> dict:
            return {"choices": [{"message": {"content": "grounded answer"}}]}

    class _Client:
        def __init__(self, *a, **k) -> None: ...
        async def __aenter__(self) -> _Client:
            return self
        async def __aexit__(self, *a) -> bool:
            return False
        async def post(self, url, json, headers):  # type: ignore[no-untyped-def]
            captured["url"] = url
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    client = OpenAICompatLLMClient("http://spark:8000/v1", "qwen3-14b")
    out = await client.complete("you are a critic", "is this grounded?")

    assert out == "grounded answer"
    assert captured["url"] == "http://spark:8000/v1/chat/completions"
    assert captured["json"]["model"] == "qwen3-14b"
    assert captured["json"]["messages"][0]["role"] == "system"
