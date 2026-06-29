"""Benchmark harness smoke test (R23)."""

from __future__ import annotations

import pytest
from provenance_eval.benchmark import benchmark_adapter, format_table
from provenance_services.embedder import DeterministicEmbedder
from provenance_services.faiss_store import FaissVectorStore
from provenance_services.qdrant_store import QdrantVectorStore


@pytest.mark.asyncio
async def test_benchmark_reports_metrics_for_faiss_and_qdrant() -> None:
    emb = DeterministicEmbedder(dim=32)
    corpus = [(f"c{i}", f"doc {i} about topic {i % 5}") for i in range(40)]
    queries = [(text, cid) for cid, text in corpus[::5]]

    for name, store in (("faiss", FaissVectorStore()), ("qdrant", QdrantVectorStore())):
        r = await benchmark_adapter(name, store, corpus, queries, emb.embed, k=5)
        assert r.n_docs == 40
        assert r.recall_at_k == 1.0  # exact-NN: each query is its own doc text
        assert r.p50_ms >= 0 and r.ingest_ms >= 0


def test_format_table_has_all_backends() -> None:
    from provenance_eval.benchmark import BenchResult

    table = format_table(
        [BenchResult("faiss", 10, 1.0, 0.1, 0.2, 1.0),
         BenchResult("pgvector", 10, 5.0, 0.5, 0.9, 1.0)],
        k=5,
    )
    assert "embedded" in table and "in-database" in table
