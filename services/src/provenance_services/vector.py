"""Vector service — the VectorStorePort as a network API (R20, R21).

P1: in-memory FAISS adapter (namespace = kb_id). Qdrant/pgvector adapters land in P6.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from provenance_contracts import VectorRecord
from provenance_service import create_app, tracer

from .vector_factory import get_vector_store

app = create_app("vector")
_store = get_vector_store()  # VECTOR_BACKEND: faiss | qdrant | pgvector (R20/N4)

# The embedding model that first populated each namespace. Reject upserts from a different
# model so real bge vectors and (e.g.) hash-fallback vectors can't silently coexist in one
# index and corrupt similarity (R66, review H-7). In-memory today; persisted with H-3.
_namespace_model: dict[str, str] = {}


@app.post("/upsert", tags=["vector"])
async def upsert(req: Request) -> dict[str, object]:
    body = await req.json()
    namespace = body.get("namespace", "default")
    model_id = body.get("model_id")
    records = [VectorRecord(**r) for r in body.get("records", [])]
    with tracer("vector").start_as_current_span("vector.upsert") as span:
        if model_id:
            existing = _namespace_model.get(namespace)
            if existing is not None and existing != model_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"namespace {namespace!r} was indexed with embedding model "
                        f"{existing!r}; refusing records from {model_id!r} (R66)"
                    ),
                )
            _namespace_model[namespace] = model_id
            span.set_attribute("vector.model_id", model_id)
        await _store.upsert(namespace, records)
        span.set_attribute("vector.upserted", len(records))
        return {"ok": True, "upserted": len(records)}


@app.post("/query", tags=["vector"])
async def query(req: Request) -> dict[str, object]:
    """Dense by default; hybrid (dense + BM25) when `text` is provided (R24)."""
    body = await req.json()
    namespace = body.get("namespace", "default")
    vector = body.get("vector", [])
    k = int(body.get("k", 5))
    filter = body.get("filter")
    text = body.get("text")
    with tracer("vector").start_as_current_span("vector.query") as span:
        if text:
            hits = await _store.hybrid_query(namespace, vector, text, k, filter)
            span.set_attribute("vector.mode", "hybrid")
        else:
            hits = await _store.query(namespace, vector, k, filter)
            span.set_attribute("vector.mode", "dense")
        return {"hits": [h.model_dump() for h in hits]}
