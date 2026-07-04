"""Vector service endpoint tests (R66, review H-7) — namespace model-id guard."""

from __future__ import annotations

from fastapi.testclient import TestClient
from provenance_services.vector import app

client = TestClient(app)


def _upsert(namespace: str, model_id: str) -> int:
    resp = client.post(
        "/upsert", json={"namespace": namespace, "model_id": model_id, "records": []}
    )
    return resp.status_code


def test_namespace_rejects_a_different_embedding_model() -> None:
    # First upsert pins the namespace's embedding model; a later upsert from a different
    # model (e.g. a hash fallback) must be refused so vectors can't silently mix (R66).
    assert _upsert("ns_a", "bge-small") == 200
    mismatch = client.post(
        "/upsert", json={"namespace": "ns_a", "model_id": "hash-fallback", "records": []}
    )
    assert mismatch.status_code == 409
    assert "refusing" in mismatch.json()["detail"]


def test_same_model_and_other_namespaces_are_unaffected() -> None:
    assert _upsert("ns_b", "bge-small") == 200
    assert _upsert("ns_b", "bge-small") == 200  # same model re-upsert is fine
    assert _upsert("ns_c", "hash-fallback") == 200  # a different namespace is independent


def test_delete_endpoint_removes_a_documents_records() -> None:
    # The compensation endpoint (H-3): upsert two docs, delete one, confirm the count.
    recs = [
        {"chunk_id": "d1_c1", "embedding": [0.1, 0.2, 0.3], "text": "a",
         "metadata": {"document_id": "d1"}},
        {"chunk_id": "d2_c1", "embedding": [0.4, 0.5, 0.6], "text": "b",
         "metadata": {"document_id": "d2"}},
    ]
    assert client.post("/upsert", json={"namespace": "ns_del", "records": recs}).status_code == 200
    r = client.post("/delete", json={"namespace": "ns_del", "document_id": "d1"})
    assert r.status_code == 200
    assert r.json()["deleted"] == 1
