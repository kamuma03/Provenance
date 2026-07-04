"""Model service — embeddings + cross-encoder reranker (R66). The only GPU service (N7).

P1: real embeddings via fastembed (deterministic fallback offline). Reranker lands in P2.
"""

from __future__ import annotations

import anyio
from fastapi import Request
from provenance_service import create_app, tracer

from .embedder import get_embedder
from .reranker import get_reranker

app = create_app("model")
_embedder = get_embedder()
_reranker = get_reranker()


@app.post("/embed", tags=["model"])
async def embed(req: Request) -> dict[str, object]:
    body = await req.json()
    texts = body.get("texts", [])
    with tracer("model").start_as_current_span("model.embed") as span:
        # ONNX embed of a whole document is CPU-bound (seconds); run it off the event loop so
        # /health and /ready keep answering under load (N7, review H-5).
        vectors = await anyio.to_thread.run_sync(_embedder.embed, texts) if texts else []
        span.set_attribute("model.embedded", len(vectors))
        return {"model_id": _embedder.model_id, "dim": _embedder.dim, "embeddings": vectors}


@app.post("/rerank", tags=["model"])
async def rerank(req: Request) -> dict[str, object]:
    """Rerank candidate documents against the query (R24). documents: [{id, text}]."""
    body = await req.json()
    query = body.get("query", "")
    documents = body.get("documents", [])
    with tracer("model").start_as_current_span("model.rerank") as span:
        texts = [d.get("text", "") for d in documents]
        scores = await anyio.to_thread.run_sync(_reranker.rerank, query, texts)
        ranked = sorted(
            ({"id": d["id"], "score": s} for d, s in zip(documents, scores, strict=False)),
            key=lambda x: x["score"],
            reverse=True,
        )
        span.set_attribute("model.reranked", len(ranked))
        return {"model_id": _reranker.model_id, "ranked": ranked}
