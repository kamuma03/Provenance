"""Qdrant adapter for the VectorStorePort (R20/R21) — the dedicated-server backend.

Namespace = collection (one per kb_id, R4). Uses Qdrant's local in-memory mode for tests
and a URL for a real server. Dense cosine search; hybrid_query falls back to dense for v1
(Qdrant-native sparse is a later enhancement). Sync client wrapped in the async Port.
"""

from __future__ import annotations

import uuid

from provenance_contracts import QueryHit, VectorRecord
from qdrant_client import QdrantClient, models

_NS = uuid.UUID("00000000-0000-0000-0000-0000000000aa")  # stable namespace for point ids


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_NS, chunk_id))


class QdrantVectorStore:
    """VectorStorePort over Qdrant. url=None → local in-memory mode."""

    def __init__(self, url: str | None = None) -> None:
        self._client = QdrantClient(location=":memory:") if url is None else QdrantClient(url=url)
        self._dims: dict[str, int] = {}

    def _ensure(self, namespace: str, dim: int) -> None:
        if not self._client.collection_exists(namespace):
            self._client.create_collection(
                collection_name=namespace,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            )
        self._dims[namespace] = dim

    async def upsert(self, namespace: str, records: list[VectorRecord]) -> None:
        if not records:
            return
        self._ensure(namespace, len(records[0].embedding))
        points = [
            models.PointStruct(
                id=_point_id(r.chunk_id),
                vector=r.embedding,
                payload={"chunk_id": r.chunk_id, "text": r.text, **r.metadata},
            )
            for r in records
        ]
        self._client.upsert(collection_name=namespace, points=points)

    def _filter(self, filter: dict[str, str] | None) -> models.Filter | None:
        if not filter:
            return None
        return models.Filter(
            must=[models.FieldCondition(key=k, match=models.MatchValue(value=v))
                  for k, v in filter.items()]
        )

    async def query(
        self, namespace: str, vector: list[float], k: int, filter: dict[str, str] | None = None
    ) -> list[QueryHit]:
        if not self._client.collection_exists(namespace):
            return []
        res = self._client.query_points(
            collection_name=namespace, query=vector, limit=k,
            query_filter=self._filter(filter), with_payload=True,
        )
        hits: list[QueryHit] = []
        for p in res.points:
            payload = p.payload or {}
            meta = {k: v for k, v in payload.items() if k not in ("chunk_id", "text")}
            hits.append(QueryHit(
                chunk_id=str(payload.get("chunk_id", p.id)), score=float(p.score),
                text=str(payload.get("text", "")), metadata={k: str(v) for k, v in meta.items()},
            ))
        return hits

    async def hybrid_query(
        self, namespace: str, vector: list[float], text: str, k: int,
        filter: dict[str, str] | None = None,
    ) -> list[QueryHit]:
        return await self.query(namespace, vector, k, filter)  # dense for v1
