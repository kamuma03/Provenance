"""Model service endpoint tests (R24/R66, review H-5) — thread-pooled inference path."""

from __future__ import annotations

from fastapi.testclient import TestClient
from provenance_services.model import app

client = TestClient(app)


def test_health_responds() -> None:
    # The point of thread-pooling inference (H-5): liveness stays answerable.
    assert client.get("/health").status_code == 200


def test_embed_returns_vectors_through_the_thread_pool() -> None:
    r = client.post("/embed", json={"texts": ["hello world", "second document"]})
    assert r.status_code == 200
    body = r.json()
    assert body["model_id"]
    assert len(body["embeddings"]) == 2
    assert body["dim"] == len(body["embeddings"][0])


def test_rerank_orders_the_relevant_document_first() -> None:
    r = client.post("/rerank", json={
        "query": "annual revenue",
        "documents": [
            {"id": "a", "text": "the weather today is pleasant and sunny"},
            {"id": "b", "text": "total annual revenue was 4.2 billion dollars"},
        ],
    })
    assert r.status_code == 200
    assert r.json()["ranked"][0]["id"] == "b"  # lexical overlap wins offline
