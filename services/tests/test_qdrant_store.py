"""Qdrant adapter tests (R20/R21/R4) — runs against Qdrant local in-memory mode."""

from __future__ import annotations

import pytest
from provenance_contracts import VectorRecord, VectorStorePort
from provenance_services.embedder import DeterministicEmbedder
from provenance_services.qdrant_store import QdrantVectorStore


def test_satisfies_vector_store_port() -> None:
    assert isinstance(QdrantVectorStore(), VectorStorePort)


@pytest.mark.asyncio
async def test_upsert_then_query_returns_nearest() -> None:
    emb = DeterministicEmbedder(dim=64)
    store = QdrantVectorStore()
    docs = {"c1": "apple revenue", "c2": "microsoft azure", "c3": "banana bread"}
    await store.upsert("kb1", [
        VectorRecord(chunk_id=cid, embedding=emb.embed([t])[0], text=t, metadata={"doc": "d1"})
        for cid, t in docs.items()
    ])
    hits = await store.query("kb1", emb.embed(["apple revenue"])[0], k=2)
    assert hits and hits[0].chunk_id == "c1"
    assert hits[0].metadata["doc"] == "d1"
    assert hits[0].text == "apple revenue"


@pytest.mark.asyncio
async def test_namespace_isolation() -> None:
    emb = DeterministicEmbedder(dim=32)
    store = QdrantVectorStore()
    await store.upsert("kbA", [VectorRecord(chunk_id="a1", embedding=emb.embed(["x"])[0])])
    await store.upsert("kbB", [VectorRecord(chunk_id="b1", embedding=emb.embed(["y"])[0])])
    hits = await store.query("kbA", emb.embed(["x"])[0], k=5)
    assert {h.chunk_id for h in hits} == {"a1"}


@pytest.mark.asyncio
async def test_metadata_filter() -> None:
    emb = DeterministicEmbedder(dim=32)
    store = QdrantVectorStore()
    await store.upsert("kb1", [
        VectorRecord(chunk_id="c1", embedding=emb.embed(["a"])[0], metadata={"page": "1"}),
        VectorRecord(chunk_id="c2", embedding=emb.embed(["b"])[0], metadata={"page": "2"}),
    ])
    hits = await store.query("kb1", emb.embed(["a"])[0], k=5, filter={"page": "2"})
    assert all(h.metadata["page"] == "2" for h in hits)
