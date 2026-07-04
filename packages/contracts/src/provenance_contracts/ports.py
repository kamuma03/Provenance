"""Ports — the swappable interfaces that become service/adapter boundaries.

The VectorStorePort is the contract every vector adapter (FAISS / Qdrant / pgvector)
implements and is literally the Vector service's API (R20, R21). Every method is
namespace-scoped so storage is partitioned per knowledge base (R4).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class VectorRecord(BaseModel):
    """A vector to upsert, keyed by chunk id (R66: embedding model recorded per index)."""

    chunk_id: str
    embedding: list[float]
    text: str = ""  # used for sparse (BM25) hybrid retrieval (R24)
    metadata: dict[str, str] = Field(default_factory=dict)


class QueryHit(BaseModel):
    chunk_id: str
    score: float
    text: str = ""  # chunk text, carried for rerank + evidence assembly
    metadata: dict[str, str] = Field(default_factory=dict)


@runtime_checkable
class VectorStorePort(Protocol):
    """Namespace-scoped vector store contract (R20). `namespace` == kb_id."""

    async def upsert(self, namespace: str, records: list[VectorRecord]) -> None: ...

    async def query(
        self,
        namespace: str,
        vector: list[float],
        k: int,
        filter: dict[str, str] | None = None,
    ) -> list[QueryHit]: ...

    async def hybrid_query(
        self,
        namespace: str,
        vector: list[float],
        text: str,
        k: int,
        filter: dict[str, str] | None = None,
    ) -> list[QueryHit]: ...

    async def delete(self, namespace: str, document_id: str) -> int:
        """Delete all records for a document; returns the count removed. Enables saga
        compensation to roll back a partial ingest (R54)."""
        ...
