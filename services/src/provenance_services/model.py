"""Model service — embeddings + cross-encoder reranker (R66). The only GPU service (N7).

P0: no-op shell. Local BGE/E5 + reranker land in P1/P2.
"""

from __future__ import annotations

from provenance_service import create_app, tracer

app = create_app("model")


@app.post("/embed", tags=["model"])
async def embed() -> dict[str, object]:
    with tracer("model").start_as_current_span("model.embed"):
        return {"dim": 0, "note": "P0 skeleton no-op"}


@app.post("/rerank", tags=["model"])
async def rerank() -> dict[str, object]:
    with tracer("model").start_as_current_span("model.rerank"):
        return {"order": [], "note": "P0 skeleton no-op"}
