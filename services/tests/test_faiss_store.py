"""FAISS adapter tests (R20/R21/R4)."""

from __future__ import annotations

import pytest
from provenance_contracts import VectorRecord, VectorStorePort
from provenance_services.embedder import DeterministicEmbedder
from provenance_services.faiss_store import FaissVectorStore


def test_satisfies_vector_store_port() -> None:
    assert isinstance(FaissVectorStore(), VectorStorePort)  # R20


@pytest.mark.asyncio
async def test_upsert_then_query_returns_nearest() -> None:
    emb = DeterministicEmbedder(dim=64)
    store = FaissVectorStore()
    texts = {"c1": "apple revenue", "c2": "microsoft azure", "c3": "banana bread"}
    records = [
        VectorRecord(chunk_id=cid, embedding=emb.embed([t])[0], metadata={"doc": "d1"})
        for cid, t in texts.items()
    ]
    await store.upsert("kb1", records)

    q = emb.embed(["apple revenue"])[0]
    hits = await store.query("kb1", q, k=2)
    assert hits and hits[0].chunk_id == "c1"  # exact match ranks first
    assert hits[0].metadata["doc"] == "d1"


@pytest.mark.asyncio
async def test_namespace_isolation() -> None:
    emb = DeterministicEmbedder(dim=32)
    store = FaissVectorStore()
    await store.upsert("kbA", [VectorRecord(chunk_id="a1", embedding=emb.embed(["x"])[0])])
    await store.upsert("kbB", [VectorRecord(chunk_id="b1", embedding=emb.embed(["y"])[0])])
    hits = await store.query("kbA", emb.embed(["x"])[0], k=5)
    assert {h.chunk_id for h in hits} == {"a1"}  # never returns kbB's vectors (R4)


@pytest.mark.asyncio
async def test_metadata_filter() -> None:
    emb = DeterministicEmbedder(dim=32)
    store = FaissVectorStore()
    await store.upsert("kb1", [
        VectorRecord(chunk_id="c1", embedding=emb.embed(["a"])[0], metadata={"page": "1"}),
        VectorRecord(chunk_id="c2", embedding=emb.embed(["b"])[0], metadata={"page": "2"}),
    ])
    hits = await store.query("kb1", emb.embed(["a"])[0], k=5, filter={"page": "2"})
    assert all(h.metadata["page"] == "2" for h in hits)


@pytest.mark.asyncio
async def test_hybrid_fuses_dense_and_sparse() -> None:
    emb = DeterministicEmbedder(dim=64)
    store = FaissVectorStore()
    docs = {
        "c1": "the quarterly revenue grew",
        "c2": "supply chain disruption risk factor",
        "c3": "board of directors meeting notes",
    }
    await store.upsert("kb1", [
        VectorRecord(chunk_id=cid, embedding=emb.embed([t])[0], text=t, metadata={})
        for cid, t in docs.items()
    ])
    # When dense (exact-vector match) and sparse (BM25 lexical) agree, the target ranks #1.
    target = docs["c2"]
    hits = await store.hybrid_query("kb1", emb.embed([target])[0], target, k=3)
    assert hits and hits[0].chunk_id == "c2"


@pytest.mark.asyncio
async def test_hybrid_falls_back_when_no_text_for_bm25() -> None:
    # Records without text => BM25 inert; hybrid still returns dense results (no crash).
    emb = DeterministicEmbedder(dim=32)
    store = FaissVectorStore()
    await store.upsert("kb1", [VectorRecord(chunk_id="c1", embedding=emb.embed(["x"])[0])])
    hits = await store.hybrid_query("kb1", emb.embed(["x"])[0], "x", k=3)
    assert [h.chunk_id for h in hits] == ["c1"]


def test_deterministic_embedder_is_stable_and_sized() -> None:
    emb = DeterministicEmbedder(dim=128)
    v1 = emb.embed(["hello"])[0]
    v2 = emb.embed(["hello"])[0]
    assert v1 == v2 and len(v1) == 128
    assert emb.embed(["world"])[0] != v1
