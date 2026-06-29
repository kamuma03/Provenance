"""FAISS adapter for the VectorStorePort (R20/R21).

Namespace-scoped (one flat cosine index per kb_id, R4). In-memory for P1; persistence
and the Qdrant/pgvector adapters land in P6. hybrid_query is dense-only for now — sparse
(BM25) fusion arrives with the retrieval core in P2.
"""

from __future__ import annotations

import faiss
import numpy as np
from provenance_contracts import QueryHit, VectorRecord


class _Namespace:
    def __init__(self, dim: int) -> None:
        self.index = faiss.IndexFlatIP(dim)  # inner product on L2-normalized = cosine
        self.ids: list[str] = []
        self.meta: list[dict[str, str]] = []
        self.dim = dim


class FaissVectorStore:
    """In-memory FAISS implementation of the VectorStorePort."""

    def __init__(self) -> None:
        self._ns: dict[str, _Namespace] = {}

    async def upsert(self, namespace: str, records: list[VectorRecord]) -> None:
        if not records:
            return
        dim = len(records[0].embedding)
        ns = self._ns.setdefault(namespace, _Namespace(dim))
        vecs = np.array([r.embedding for r in records], dtype="float32")
        faiss.normalize_L2(vecs)
        ns.index.add(vecs)
        ns.ids.extend(r.chunk_id for r in records)
        ns.meta.extend(r.metadata for r in records)

    async def query(
        self,
        namespace: str,
        vector: list[float],
        k: int,
        filter: dict[str, str] | None = None,
    ) -> list[QueryHit]:
        ns = self._ns.get(namespace)
        if ns is None or ns.index.ntotal == 0:
            return []
        q = np.array([vector], dtype="float32")
        faiss.normalize_L2(q)
        # Over-fetch when filtering, then post-filter on metadata.
        fetch = min(k * 4 if filter else k, ns.index.ntotal)
        scores, idxs = ns.index.search(q, fetch)
        hits: list[QueryHit] = []
        for score, i in zip(scores[0], idxs[0], strict=False):
            if i < 0:
                continue
            meta = ns.meta[i]
            if filter and not all(meta.get(fk) == fv for fk, fv in filter.items()):
                continue
            hits.append(QueryHit(chunk_id=ns.ids[i], score=float(score), metadata=meta))
            if len(hits) >= k:
                break
        return hits

    async def hybrid_query(
        self,
        namespace: str,
        vector: list[float],
        text: str,
        k: int,
        filter: dict[str, str] | None = None,
    ) -> list[QueryHit]:
        # Dense-only for P1; BM25 sparse fusion arrives with the retrieval core (P2).
        return await self.query(namespace, vector, k, filter)
