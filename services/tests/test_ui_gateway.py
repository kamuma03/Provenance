"""Pre-implementation (RED) tests for the UI-redesign Gateway surface.

Maps to spec.md: R-BE-1 (list KBs), R-BE-2 (kb_ids on the query edge),
R-BE-4 (live crew stage events + no-unverified-token ordering + text parity),
R-BE-5 (chunk fetch), R-BE-7 (ingest events SSE route).
Style matches test_gateway.py (TestClient + monkeypatch, fully offline).
These FAIL until the routes/behaviours exist.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from provenance_services import gateway

client = TestClient(gateway.app)


def _answer_result(text: str = "total revenue was 4.2 billion") -> dict:
    return {
        "answer": {"text": text, "refused": False, "claims": []},
        "evidence": {"subquery": "q", "chunks": [], "entity_ids": [], "graph_expanded": False},
    }


# ------------------------------------------------------------- R-BE-1 · list KBs
def test_get_kb_lists_knowledge_bases(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list():  # type: ignore[no-untyped-def]
        return [{"id": "kb1", "name": "Acme 10-K", "domain_id": "sec_financial",
                 "created_at": "2026-01-01T00:00:00Z"}]

    monkeypatch.setattr(gateway.catalog, "list_kb", fake_list, raising=False)
    r = client.get("/kb")
    assert r.status_code == 200  # red: no GET /kb route today (404)
    body = r.json()
    assert isinstance(body, list) and body[0]["id"] == "kb1"
    assert body[0]["name"] == "Acme 10-K"


# ---------------------------------------------------- R-BE-2 · kb_ids on the edge
def test_query_accepts_kb_ids_list(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_call(service, path, payload=None):  # type: ignore[no-untyped-def]
        captured.update(payload or {})
        return _answer_result()

    monkeypatch.setattr(gateway, "call", fake_call)
    r = client.post("/query", json={"kb_ids": ["a", "b"], "query": "q"})
    assert r.status_code == 200
    assert captured.get("kb_ids") == ["a", "b"]  # red: QueryRequest has only kb_id today


def test_query_legacy_kb_id_still_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_call(service, path, payload=None):  # type: ignore[no-untyped-def]
        captured.update(payload or {})
        return _answer_result()

    monkeypatch.setattr(gateway, "call", fake_call)
    r = client.post("/query", json={"kb_id": "solo", "query": "q"})
    assert r.status_code == 200
    # legacy kb_id must be normalized into kb_ids=[kb_id] for a dual-running release
    assert captured.get("kb_ids") == ["solo"]  # red until alias handling exists


# ------------------------------------- R-BE-4 · live crew streaming (no unverified tokens)
def test_query_stream_emits_all_four_crew_stage_events(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call(service, path, payload=None):  # type: ignore[no-untyped-def]
        return _answer_result()

    monkeypatch.setattr(gateway, "call", fake_call)
    with client.stream("POST", "/query/stream", json={"kb_id": "kb", "query": "q"}) as r:
        body = "".join(r.iter_text())
    for stage in ("planner", "retriever", "critic", "synthesizer"):
        assert stage in body  # red: today only "retrieving"/"synthesizing" phases


def test_query_stream_tokens_only_after_critic_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strict groundedness (R31/R32): answer tokens must not be streamed before the Critic
    approves — no speculative/unverified text reaches the browser."""
    async def fake_call(service, path, payload=None):  # type: ignore[no-untyped-def]
        return _answer_result()

    monkeypatch.setattr(gateway, "call", fake_call)
    with client.stream("POST", "/query/stream", json={"kb_id": "kb", "query": "q"}) as r:
        body = "".join(r.iter_text())
    critic_ix = body.find("critic")
    first_token_ix = body.find("event: token")
    assert critic_ix != -1
    assert first_token_ix == -1 or first_token_ix > critic_ix  # red until reordered


def test_query_stream_text_parity_with_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The streamed tokens must reconstruct exactly the (verified) answer text — the stream is
    a presentation of the computed answer, never a different one (core constraint #1)."""
    async def fake_call(service, path, payload=None):  # type: ignore[no-untyped-def]
        return _answer_result("total revenue was 4.2 billion")

    monkeypatch.setattr(gateway, "call", fake_call)
    with client.stream("POST", "/query/stream", json={"kb_id": "kb", "query": "q"}) as r:
        body = "".join(r.iter_text())
    assert "synthesizer" in body  # tokens come from the new synthesizer stage (red today)
    # Parse only `event: token` SSE blocks (ignore the `done` event's answer JSON).
    tokens: list[str] = []
    for block in body.split("\n\n"):
        if "event: token" not in block:
            continue
        data = "".join(ln[len("data:"):].strip() for ln in block.splitlines()
                        if ln.startswith("data:"))
        tokens.append(json.loads(data)["text"])
    assert "".join(tokens).strip() == "total revenue was 4.2 billion"


# ------------------------------------------------------------- R-BE-5 · chunk fetch
def test_get_chunk_returns_span_with_bbox(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_chunk(cid):  # type: ignore[no-untyped-def]
        return {"id": cid, "text": "total revenue was $4.2B", "page": 42,
                "bbox": {"page": 42, "x0": 72, "y0": 512, "x1": 388, "y1": 536}}

    monkeypatch.setattr(gateway.catalog, "get_chunk", fake_get_chunk, raising=False)
    r = client.get("/chunks/c_0421")
    assert r.status_code == 200  # red: no GET /chunks/{id} route today (404)
    body = r.json()
    assert body["page"] == 42 and body["bbox"]["x1"] == 388


# ------------------------------------------------- R-BE-7 · live ingest SSE route
def test_document_events_route_streams_sse() -> None:
    with client.stream("GET", "/documents/d1/events") as r:
        assert r.status_code == 200  # red: no route today (404)
        assert "text/event-stream" in r.headers.get("content-type", "")
