"""Query/Agent service — retrieval core + (P3) the 4-agent crew (R28–R33, R53).

P2: exposes the real retrieval core via /retrieve (R30). Only this service fans out to
Model + Vector + Graph (R53). The Planner/Critic/Synthesizer crew lands in P3; /answer
currently returns the retrieved evidence with a placeholder synthesis.
"""

from __future__ import annotations

from fastapi import Request
from provenance_contracts import Answer, QueryHit
from provenance_service import create_app, tracer

from .clients import call
from .retrieval import RetrievalDeps, retrieve

app = create_app("query-agent")


async def _embed(query: str) -> list[float]:
    resp = await call("model", "/embed", {"texts": [query]})
    embs = resp.get("embeddings", [])
    return embs[0] if embs else []


async def _hybrid(kb_id: str, vector: list[float], text: str, k: int) -> list[QueryHit]:
    payload = {"namespace": kb_id, "vector": vector, "text": text, "k": k}
    resp = await call("vector", "/query", payload)
    return [QueryHit(**h) for h in resp.get("hits", [])]


async def _rerank(query: str, hits: list[QueryHit]) -> list[QueryHit]:
    if not hits:
        return hits
    docs = [{"id": h.chunk_id, "text": h.text} for h in hits]
    resp = await call("model", "/rerank", {"query": query, "documents": docs})
    order = {d["id"]: i for i, d in enumerate(resp.get("ranked", []))}
    return sorted(hits, key=lambda h: order.get(h.chunk_id, len(hits)))


async def _link(kb_id: str, text: str) -> list[str]:
    resp = await call("graph", "/link", {"kb_id": kb_id, "text": text})
    return resp.get("entity_ids", [])


async def _expand(entity_ids: list[str]) -> list[str]:
    out: list[str] = []
    for eid in entity_ids:
        resp = await call("graph", "/expand", {"entity_id": eid})
        out.extend(resp.get("entities", []))
    return out


def _deps() -> RetrievalDeps:
    return RetrievalDeps(embed=_embed, hybrid=_hybrid, rerank=_rerank, link=_link, expand=_expand)


@app.post("/retrieve", tags=["query"])
async def retrieve_endpoint(req: Request) -> dict[str, object]:
    """Resolve a query to an EvidenceSet via the retrieval core (R30)."""
    body = await req.json()
    kb_id = body.get("kb_id", "default")
    query = body.get("query", "")
    with tracer("query-agent").start_as_current_span("query.retrieve") as span:
        evidence = await retrieve(kb_id, query, _deps(), k=int(body.get("k", 5)))
        span.set_attribute("retrieve.chunks", len(evidence.chunks))
        span.set_attribute("retrieve.graph_expanded", evidence.graph_expanded)
        return evidence.model_dump()


@app.post("/answer", tags=["query"])
async def answer(req: Request) -> dict[str, object]:
    """P2: return retrieved evidence + placeholder synthesis (the crew lands in P3)."""
    body = await req.json()
    kb_id = body.get("kb_id", "default")
    query = body.get("query", "")
    with tracer("query-agent").start_as_current_span("query.answer"):
        evidence = await retrieve(kb_id, query, _deps())
        ans = Answer(
            text="(P2 retrieval core — synthesis + Critic land in P3)",
            refused=not evidence.chunks,
        )
        return {"query": query, "evidence": evidence.model_dump(), "answer": ans.model_dump()}
