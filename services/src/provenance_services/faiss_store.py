"""FAISS adapter for the VectorStorePort (R20/R21/R24).

Namespace-scoped (one index per kb_id, R4). Dense retrieval via FAISS cosine; sparse via
BM25; hybrid fuses both with reciprocal rank fusion (R24). In-memory for P1/P2; persistence
and the Qdrant/pgvector adapters land in P6.
"""

from __future__ import annotations

import faiss
import numpy as np
from provenance_contracts import QueryHit, VectorRecord
from rank_bm25 import BM25Okapi

RRF_K = 60  # reciprocal-rank-fusion constant


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


class _Namespace:
    def __init__(self, dim: int) -> None:
        self.index = faiss.IndexFlatIP(dim)  # inner product on L2-normalized = cosine
        self.ids: list[str] = []
        self.meta: list[dict[str, str]] = []
        self.texts: list[str] = []  # for BM25 sparse retrieval (R24)
        self.dim = dim
        self._bm25: BM25Okapi | None = None
        self._dirty = True

    def bm25(self) -> BM25Okapi | None:
        if not any(self.texts):
            return None
        if self._dirty or self._bm25 is None:
            self._bm25 = BM25Okapi([_tokenize(t) for t in self.texts])
            self._dirty = False
        return self._bm25


class FaissVectorStore:
    """In-memory FAISS + BM25 implementation of the VectorStorePort."""

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
        ns.texts.extend(r.text for r in records)
        ns._dirty = True

    def _passes(self, meta: dict[str, str], filter: dict[str, str] | None) -> bool:
        return not filter or all(meta.get(fk) == fv for fk, fv in filter.items())

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
        fetch = min(k * 4 if filter else k, ns.index.ntotal)
        scores, idxs = ns.index.search(q, fetch)
        hits: list[QueryHit] = []
        for score, i in zip(scores[0], idxs[0], strict=False):
            if i < 0 or not self._passes(ns.meta[i], filter):
                continue
            hits.append(
                QueryHit(
                    chunk_id=ns.ids[i], score=float(score),
                    text=ns.texts[i], metadata=ns.meta[i],
                )
            )
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
        """Dense + BM25 fused by reciprocal rank fusion (R24)."""
        ns = self._ns.get(namespace)
        if ns is None or ns.index.ntotal == 0:
            return []

        # Dense ranking (by index position).
        dense = await self.query(namespace, vector, k=ns.index.ntotal, filter=None)
        dense_rank = {h.chunk_id: r for r, h in enumerate(dense)}

        # Sparse ranking via BM25.
        sparse_rank: dict[str, int] = {}
        bm25 = ns.bm25()
        if bm25 is not None and text.strip():
            scores = bm25.get_scores(_tokenize(text))
            order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            for r, i in enumerate(order):
                sparse_rank[ns.ids[i]] = r

        # Fuse.
        meta_by_id = dict(zip(ns.ids, ns.meta, strict=False))
        text_by_id = dict(zip(ns.ids, ns.texts, strict=False))
        fused: dict[str, float] = {}
        for cid in set(dense_rank) | set(sparse_rank):
            if not self._passes(meta_by_id.get(cid, {}), filter):
                continue
            score = 0.0
            if cid in dense_rank:
                score += 1.0 / (RRF_K + dense_rank[cid])
            if cid in sparse_rank:
                score += 1.0 / (RRF_K + sparse_rank[cid])
            fused[cid] = score

        ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
        return [
            QueryHit(
                chunk_id=cid, score=s,
                text=text_by_id.get(cid, ""), metadata=meta_by_id.get(cid, {}),
            )
            for cid, s in ranked
        ]
