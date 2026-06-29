"""Port-compatible stubs for OpenSearch and Weaviate (R21).

These satisfy the VectorStorePort surface so the factory can route to them, but raise
NotImplementedError cleanly — they exist to prove the Port is vendor-agnostic and to mark
where the OpenSearch (OSS + AWS-managed bridge) and Weaviate adapters slot in.
"""

from __future__ import annotations

from provenance_contracts import QueryHit, VectorRecord


class _StubStore:
    backend = "stub"

    async def upsert(self, namespace: str, records: list[VectorRecord]) -> None:
        raise NotImplementedError(f"{self.backend} adapter not implemented yet")

    async def query(
        self, namespace: str, vector: list[float], k: int, filter: dict[str, str] | None = None
    ) -> list[QueryHit]:
        raise NotImplementedError(f"{self.backend} adapter not implemented yet")

    async def hybrid_query(
        self, namespace: str, vector: list[float], text: str, k: int,
        filter: dict[str, str] | None = None,
    ) -> list[QueryHit]:
        raise NotImplementedError(f"{self.backend} adapter not implemented yet")


class OpenSearchVectorStore(_StubStore):
    backend = "opensearch"


class WeaviateVectorStore(_StubStore):
    backend = "weaviate"
