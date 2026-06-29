"""Model service — embeddings + cross-encoder reranker (R66). The only GPU service (N7).

P1: real embeddings via fastembed (deterministic fallback offline). Reranker lands in P2.
"""

from __future__ import annotations

from fastapi import Request
from provenance_service import create_app, tracer

from .embedder import get_embedder

app = create_app("model")
_embedder = get_embedder()


@app.post("/embed", tags=["model"])
async def embed(req: Request) -> dict[str, object]:
    body = await req.json()
    texts = body.get("texts", [])
    with tracer("model").start_as_current_span("model.embed") as span:
        vectors = _embedder.embed(texts) if texts else []
        span.set_attribute("model.embedded", len(vectors))
        return {"model_id": _embedder.model_id, "dim": _embedder.dim, "embeddings": vectors}


@app.post("/rerank", tags=["model"])
async def rerank() -> dict[str, object]:
    with tracer("model").start_as_current_span("model.rerank"):
        return {"order": [], "note": "cross-encoder rerank lands in P2"}
