"""Vector-backend benchmark (R23) — embedded vs dedicated-server vs in-database.

Ingests a fixed corpus into each adapter, runs a query set, and reports ingest time,
p50/p95 query latency, and recall@k. Deterministic embeddings make recall a sanity check
(exact-NN); the headline comparison is latency across the three architectures.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass

from provenance_contracts import VectorRecord, VectorStorePort

EmbedFn = Callable[[list[str]], list[list[float]]]


@dataclass
class BenchResult:
    backend: str
    n_docs: int
    ingest_ms: float
    p50_ms: float
    p95_ms: float
    recall_at_k: float


async def benchmark_adapter(
    backend: str,
    store: VectorStorePort,
    corpus: list[tuple[str, str]],
    queries: list[tuple[str, str]],
    embed: EmbedFn,
    k: int = 5,
) -> BenchResult:
    records = [
        VectorRecord(chunk_id=cid, embedding=embed([text])[0], text=text)
        for cid, text in corpus
    ]
    t0 = time.perf_counter()
    await store.upsert("bench", records)
    ingest_ms = (time.perf_counter() - t0) * 1000

    latencies: list[float] = []
    hits = 0
    for qtext, gold in queries:
        qv = embed([qtext])[0]
        t1 = time.perf_counter()
        res = await store.query("bench", qv, k)
        latencies.append((time.perf_counter() - t1) * 1000)
        if gold in {h.chunk_id for h in res}:
            hits += 1

    latencies.sort()
    return BenchResult(
        backend=backend,
        n_docs=len(corpus),
        ingest_ms=round(ingest_ms, 1),
        p50_ms=round(statistics.median(latencies), 2),
        p95_ms=round(latencies[int(len(latencies) * 0.95)], 2),
        recall_at_k=round(hits / len(queries), 3),
    )


def format_table(results: list[BenchResult], k: int) -> str:
    lines = [
        f"| Backend | Architecture | Docs | Ingest (ms) | p50 query (ms) | p95 (ms) | Recall@{k} |",
        "|---|---|---|---|---|---|---|",
    ]
    arch = {"faiss": "embedded", "qdrant": "dedicated server", "pgvector": "in-database"}
    for r in results:
        lines.append(
            f"| {r.backend} | {arch.get(r.backend, '?')} | {r.n_docs} | "
            f"{r.ingest_ms} | {r.p50_ms} | {r.p95_ms} | {r.recall_at_k} |"
        )
    return "\n".join(lines)
