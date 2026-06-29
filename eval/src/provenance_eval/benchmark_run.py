"""Run the vector-backend benchmark (R23) and write docs/benchmark.md.

Always benchmarks FAISS (embedded) + Qdrant (in-memory server mode). Includes pgvector
(in-database) when PGVECTOR_DSN is set (e.g. a pgvector/pgvector container).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from provenance_services.embedder import DeterministicEmbedder
from provenance_services.faiss_store import FaissVectorStore
from provenance_services.qdrant_store import QdrantVectorStore

from .benchmark import BenchResult, benchmark_adapter, format_table

_WORDS = ["revenue", "auditor", "merger", "risk", "supply", "patent", "clause", "dataset",
          "method", "dividend", "subsidiary", "board", "fiscal", "liability", "asset"]
K = 5
OUT = Path(__file__).resolve().parents[3] / "docs" / "benchmark.md"


def _corpus(n: int) -> list[tuple[str, str]]:
    return [(f"c{i}", f"document {i} discussing the {_WORDS[i % len(_WORDS)]} topic in detail")
            for i in range(n)]


def _queries(corpus: list[tuple[str, str]], step: int) -> list[tuple[str, str]]:
    return [(text, cid) for cid, text in corpus[::step]]


async def _run(n_docs: int) -> list[BenchResult]:
    emb = DeterministicEmbedder(dim=64)
    corpus = _corpus(n_docs)
    queries = _queries(corpus, step=4)
    results: list[BenchResult] = []

    results.append(
        await benchmark_adapter("faiss", FaissVectorStore(), corpus, queries, emb.embed, K)
    )
    results.append(
        await benchmark_adapter("qdrant", QdrantVectorStore(), corpus, queries, emb.embed, K)
    )

    dsn = os.environ.get("PGVECTOR_DSN")
    if dsn:
        from provenance_services.pgvector_store import PgVectorStore
        store = PgVectorStore(dsn)
        results.append(await benchmark_adapter("pgvector", store, corpus, queries, emb.embed, K))
        await store.close()
    return results


def main(n_docs: int = 500) -> int:
    results = asyncio.run(_run(n_docs))
    table = format_table(results, K)
    print(table)
    has_pg = bool(os.environ.get("PGVECTOR_DSN"))
    note = "" if has_pg else "\n> pgvector row omitted (set PGVECTOR_DSN).\n"
    OUT.write_text(
        "# Vector-backend benchmark\n\n"
        "Embedded vs dedicated-server vs in-database, behind one `VectorStorePort` (R23).\n"
        "Deterministic embeddings ⇒ recall is an exact-NN sanity check; the comparison is\n"
        "latency across architectures. Run: `python -m provenance_eval.benchmark_run`.\n\n"
        f"{table}\n{note}"
    )
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
