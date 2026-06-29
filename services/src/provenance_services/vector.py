"""Vector service — the VectorStorePort as a network API (R20, R21).

P1: in-memory FAISS adapter (namespace = kb_id). Qdrant/pgvector adapters land in P6.
"""

from __future__ import annotations

from fastapi import Request
from provenance_contracts import VectorRecord
from provenance_service import create_app, tracer

from .faiss_store import FaissVectorStore

app = create_app("vector")
_store = FaissVectorStore()


@app.post("/upsert", tags=["vector"])
async def upsert(req: Request) -> dict[str, object]:
    body = await req.json()
    namespace = body.get("namespace", "default")
    records = [VectorRecord(**r) for r in body.get("records", [])]
    with tracer("vector").start_as_current_span("vector.upsert") as span:
        await _store.upsert(namespace, records)
        span.set_attribute("vector.upserted", len(records))
        return {"ok": True, "upserted": len(records)}


@app.post("/query", tags=["vector"])
async def query(req: Request) -> dict[str, object]:
    body = await req.json()
    with tracer("vector").start_as_current_span("vector.query"):
        hits = await _store.query(
            body.get("namespace", "default"),
            body.get("vector", []),
            int(body.get("k", 5)),
            body.get("filter"),
        )
        return {"hits": [h.model_dump() for h in hits]}
