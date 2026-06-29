"""Vector service — the VectorStorePort as a network API (R20, R21).

P0: no-op shell. FAISS/Qdrant/pgvector adapters land in P1/P6.
"""

from __future__ import annotations

from provenance_service import create_app, tracer

app = create_app("vector")


@app.post("/upsert", tags=["vector"])
async def upsert() -> dict[str, object]:
    with tracer("vector").start_as_current_span("vector.upsert"):
        return {"ok": True, "note": "P0 skeleton no-op"}


@app.post("/query", tags=["vector"])
async def query() -> dict[str, object]:
    with tracer("vector").start_as_current_span("vector.query"):
        return {"hits": [], "note": "P0 skeleton no-op"}
