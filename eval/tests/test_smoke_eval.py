"""Smoke eval test (R45) — in-process retrieval recall over a tiny corpus.

Builds a real FAISS+BM25 store with a deterministic embedder (no network), so the smoke
eval is fully self-contained and exercises the actual hybrid retrieval path.
"""

from __future__ import annotations

import pytest
from provenance_contracts import VectorRecord
from provenance_eval.smoke import SMOKE_RECALL_THRESHOLD, retrieval_recall
from provenance_services.embedder import DeterministicEmbedder
from provenance_services.faiss_store import FaissVectorStore


@pytest.mark.asyncio
async def test_retrieval_recall_meets_threshold() -> None:
    emb = DeterministicEmbedder(dim=64)
    store = FaissVectorStore()
    corpus = {
        "c1": "the independent auditor is Ernst and Young",
        "c2": "total revenue for fiscal 2022 was 4.2 billion dollars",
        "c3": "the board of directors approved the merger",
    }
    await store.upsert("kb1", [
        VectorRecord(chunk_id=cid, embedding=emb.embed([t])[0], text=t)
        for cid, t in corpus.items()
    ])

    async def retrieve_fn(query: str, k: int) -> list[str]:
        hits = await store.hybrid_query("kb1", emb.embed([query])[0], query, k)
        return [h.chunk_id for h in hits]

    cases = [
        ("who is the independent auditor", {"c1"}),
        ("total revenue fiscal 2022", {"c2"}),
        ("board of directors merger", {"c3"}),
    ]
    recall = await retrieval_recall(retrieve_fn, cases, k=2)
    assert recall >= SMOKE_RECALL_THRESHOLD, f"retrieval recall {recall} below smoke gate"


@pytest.mark.asyncio
async def test_recall_is_zero_for_no_cases() -> None:
    async def noop(_q: str, _k: int) -> list[str]:
        return []

    assert await retrieval_recall(noop, [], k=5) == 0.0
