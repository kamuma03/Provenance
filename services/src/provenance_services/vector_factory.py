"""Config-driven VectorStorePort selection (R20/N4).

One contract, many backends — the swap that powers the benchmark and the on-prem↔cloud
story. Pick via VECTOR_BACKEND (faiss | qdrant | pgvector | opensearch | weaviate).
"""

from __future__ import annotations

import os

from provenance_contracts import VectorStorePort


def _pgvector_dsn() -> str:
    """The Vector service owns its own database (R52) — it must NOT reuse the Gateway
    catalog's DSN. Require a dedicated PGVECTOR_DSN with no catalog fallback (review H-10)."""
    dsn = os.environ.get("PGVECTOR_DSN")
    if not dsn:
        raise RuntimeError(
            "VECTOR_BACKEND=pgvector requires PGVECTOR_DSN (its own database, per R52); "
            "it must not share the Gateway catalog's connection string."
        )
    return dsn


def get_vector_store(backend: str | None = None) -> VectorStorePort:
    backend = (backend or os.environ.get("VECTOR_BACKEND", "faiss")).lower()
    if backend == "faiss":
        from .faiss_store import FaissVectorStore
        return FaissVectorStore()
    if backend == "qdrant":
        from .qdrant_store import QdrantVectorStore
        return QdrantVectorStore(os.environ.get("QDRANT_URL"))
    if backend == "pgvector":
        dsn = _pgvector_dsn()  # validate first (R52), independent of driver availability
        from .pgvector_store import PgVectorStore
        return PgVectorStore(dsn)
    if backend == "opensearch":
        from .vendor_stubs import OpenSearchVectorStore
        return OpenSearchVectorStore()
    if backend == "weaviate":
        from .vendor_stubs import WeaviateVectorStore
        return WeaviateVectorStore()
    raise ValueError(f"unknown VECTOR_BACKEND: {backend}")
