"""Vector service — the VectorStorePort as a network API (R20, R21).

P1: in-memory FAISS adapter (namespace = kb_id). Qdrant/pgvector adapters land in P6.
"""

from __future__ import annotations

from fastapi import HTTPException
from provenance_contracts import VectorRecord
from provenance_service import create_app, tracer
from pydantic import BaseModel, Field

from .vector_factory import get_vector_store

app = create_app("vector")
_store = get_vector_store()  # VECTOR_BACKEND: faiss | qdrant | pgvector (R20/N4)

# The embedding model that first populated each namespace. Reject upserts from a different
# model so real bge vectors and (e.g.) hash-fallback vectors can't silently coexist in one
# index and corrupt similarity (R66, review H-7). In-memory today; persisted with H-3.
_namespace_model: dict[str, str] = {}


# Typed internal request bodies (N9, review M-5).
class UpsertRequest(BaseModel):
    namespace: str = "default"
    model_id: str | None = None
    records: list[VectorRecord] = Field(default_factory=list)


class DeleteRequest(BaseModel):
    namespace: str = "default"
    document_id: str = ""


class QueryRequest(BaseModel):
    namespace: str = "default"
    vector: list[float] = Field(default_factory=list)
    k: int = 5
    filter: dict[str, str] | None = None
    text: str | None = None


@app.post("/upsert", tags=["vector"])
async def upsert(body: UpsertRequest) -> dict[str, object]:
    with tracer("vector").start_as_current_span("vector.upsert") as span:
        if body.model_id:
            existing = _namespace_model.get(body.namespace)
            if existing is not None and existing != body.model_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"namespace {body.namespace!r} was indexed with embedding model "
                        f"{existing!r}; refusing records from {body.model_id!r} (R66)"
                    ),
                )
            _namespace_model[body.namespace] = body.model_id
            span.set_attribute("vector.model_id", body.model_id)
        await _store.upsert(body.namespace, body.records)
        span.set_attribute("vector.upserted", len(body.records))
        return {"ok": True, "upserted": len(body.records)}


@app.post("/delete", tags=["vector"])
async def delete(body: DeleteRequest) -> dict[str, object]:
    """Delete a document's records (saga compensation, R54/H-3)."""
    with tracer("vector").start_as_current_span("vector.delete") as span:
        removed = await _store.delete(body.namespace, body.document_id) if body.document_id else 0
        span.set_attribute("vector.deleted", removed)
        return {"deleted": removed}


@app.post("/query", tags=["vector"])
async def query(body: QueryRequest) -> dict[str, object]:
    """Dense by default; hybrid (dense + BM25) when `text` is provided (R24)."""
    with tracer("vector").start_as_current_span("vector.query") as span:
        if body.text:
            hits = await _store.hybrid_query(
                body.namespace, body.vector, body.text, body.k, body.filter
            )
            span.set_attribute("vector.mode", "hybrid")
        else:
            hits = await _store.query(body.namespace, body.vector, body.k, body.filter)
            span.set_attribute("vector.mode", "dense")
        return {"hits": [h.model_dump() for h in hits]}
