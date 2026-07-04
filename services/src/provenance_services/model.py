"""Model service — embeddings + cross-encoder reranker (R66). The only GPU service (N7).

P1: real embeddings via fastembed (deterministic fallback offline). Reranker lands in P2.
"""

from __future__ import annotations

import anyio
from provenance_service import create_app, tracer
from pydantic import BaseModel, Field

from .embedder import get_embedder
from .reranker import get_reranker

app = create_app("model")
_embedder = get_embedder()
_reranker = get_reranker()


# Typed internal request bodies (N9, review M-5): validated by FastAPI + surfaced in OpenAPI.
class EmbedRequest(BaseModel):
    texts: list[str] = Field(default_factory=list)


class RerankDoc(BaseModel):
    id: str
    text: str = ""


class RerankRequest(BaseModel):
    query: str = ""
    documents: list[RerankDoc] = Field(default_factory=list)


@app.post("/embed", tags=["model"])
async def embed(body: EmbedRequest) -> dict[str, object]:
    with tracer("model").start_as_current_span("model.embed") as span:
        # ONNX embed of a whole document is CPU-bound (seconds); run it off the event loop so
        # /health and /ready keep answering under load (N7, review H-5).
        vectors = await anyio.to_thread.run_sync(_embedder.embed, body.texts) if body.texts else []
        span.set_attribute("model.embedded", len(vectors))
        return {"model_id": _embedder.model_id, "dim": _embedder.dim, "embeddings": vectors}


@app.post("/rerank", tags=["model"])
async def rerank(body: RerankRequest) -> dict[str, object]:
    """Rerank candidate documents against the query (R24). documents: [{id, text}]."""
    with tracer("model").start_as_current_span("model.rerank") as span:
        texts = [d.text for d in body.documents]
        scores = await anyio.to_thread.run_sync(_reranker.rerank, body.query, texts)
        scored = sorted(
            zip(body.documents, scores, strict=False), key=lambda ds: ds[1], reverse=True
        )
        ranked = [{"id": d.id, "score": s} for d, s in scored]
        span.set_attribute("model.reranked", len(ranked))
        return {"model_id": _reranker.model_id, "ranked": ranked}
