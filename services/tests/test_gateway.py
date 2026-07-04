"""Gateway upload tests (N5, review H-4) — idempotency + input validation."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from provenance_services import gateway

client = TestClient(gateway.app)


def test_malformed_base64_returns_400() -> None:
    r = client.post("/kb/kb1/documents", json={"content_b64": "not valid base64 !!!"})
    assert r.status_code == 400
    assert "base64" in r.json()["error"]


def test_duplicate_upload_returns_existing_id_and_skips_the_saga(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[str] = []

    async def fake_create(doc_id, kb_id, source, content_type, content_hash):  # type: ignore[no-untyped-def]
        return ("doc_existing", False)  # simulate an ON CONFLICT hit

    async def fake_publish(subject, data):  # type: ignore[no-untyped-def]
        published.append(subject)

    monkeypatch.setattr(gateway.catalog, "create_document", fake_create)
    monkeypatch.setattr(gateway.bus, "publish", fake_publish)

    r = client.post("/kb/kb1/documents", json={"content": "hello"})
    assert r.status_code == 200
    assert r.json() == {"document_id": "doc_existing", "status": "duplicate"}
    assert published == []  # the saga is NOT re-run on a duplicate (H-4)


def test_new_upload_publishes_and_returns_202(monkeypatch: pytest.MonkeyPatch) -> None:
    published: list[str] = []

    async def fake_create(doc_id, kb_id, source, content_type, content_hash):  # type: ignore[no-untyped-def]
        return (doc_id, True)  # fresh insert

    async def fake_publish(subject, data):  # type: ignore[no-untyped-def]
        published.append(subject)

    monkeypatch.setattr(gateway.catalog, "create_document", fake_create)
    monkeypatch.setattr(gateway.bus, "publish_durable", fake_publish)

    r = client.post("/kb/kb1/documents", json={"content": "hello world"})
    assert r.status_code == 202
    assert r.json()["status"] == "queued"
    assert published == ["ingest.jobs"]  # saga enqueued exactly once (durable publish)


@pytest.mark.asyncio
async def test_done_status_event_persists_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    # A 'done' event carrying provenance must be written to the Document row (R56, H-9),
    # not routed through the bare status update.
    recorded: dict[str, object] = {}

    async def fake_record(doc_id, status, provenance):  # type: ignore[no-untyped-def]
        recorded.update(doc=doc_id, status=status, prov=provenance)

    async def fake_update(doc_id, status):  # type: ignore[no-untyped-def]
        recorded["bare_update"] = True

    monkeypatch.setattr(gateway.catalog, "record_provenance", fake_record)
    monkeypatch.setattr(gateway.catalog, "update_status", fake_update)

    evt = json.dumps({
        "document_id": "d1", "status": "done",
        "provenance": {"detected_domain": "sec_financial", "trace_id": "trace-xyz"},
    }).encode()
    await gateway._on_status(evt, {})

    assert recorded["doc"] == "d1"
    assert recorded["prov"]["trace_id"] == "trace-xyz"  # type: ignore[index]
    assert "bare_update" not in recorded  # provenance path taken, not the plain update


@pytest.mark.asyncio
async def test_intermediate_status_event_uses_plain_update(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_update(doc_id, status):  # type: ignore[no-untyped-def]
        calls.append((doc_id, status))

    monkeypatch.setattr(gateway.catalog, "update_status", fake_update)
    await gateway._on_status(json.dumps({"document_id": "d2", "status": "extracting"}).encode(), {})
    assert calls == [("d2", "extracting")]


def test_query_endpoint_rejects_missing_query_field() -> None:
    # The typed edge validates input instead of silently defaulting to an empty query (M-5).
    r = client.post("/query", json={"kb_id": "kb"})  # no 'query'
    assert r.status_code == 422


def test_query_stream_makes_a_single_backend_call_and_streams_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One /answer call (not /retrieve + /answer), and the done event carries its evidence (M-15).
    paths: list[str] = []

    async def fake_call(service, path, payload=None):  # type: ignore[no-untyped-def]
        paths.append(path)
        return {
            "answer": {"text": "hello world", "refused": False, "claims": []},
            "evidence": {"subquery": "q", "chunks": [], "entity_ids": [], "graph_expanded": False},
        }

    monkeypatch.setattr(gateway, "call", fake_call)
    with client.stream("POST", "/query/stream", json={"kb_id": "kb", "query": "q"}) as r:
        body = "".join(r.iter_text())
    assert paths == ["/answer"]  # single retrieval path
    assert "event: done" in body and "hello" in body


def test_query_stream_emits_error_event_on_backend_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(service, path, payload=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("query service down")

    monkeypatch.setattr(gateway, "call", boom)
    with client.stream("POST", "/query/stream", json={"kb_id": "kb", "query": "q"}) as r:
        body = "".join(r.iter_text())
    assert "event: error" in body  # UI stops spinning instead of hanging
