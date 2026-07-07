"""Query/Agent service — retrieval core + (P3) the 4-agent crew (R28–R33, R53).

P2: exposes the real retrieval core via /retrieve (R30). Only this service fans out to
Model + Vector + Graph (R53). The Planner/Critic/Synthesizer crew lands in P3; /answer
currently returns the retrieved evidence with a placeholder synthesis.
"""

from __future__ import annotations

from typing import cast

from fastapi import Request
from provenance_contracts import (
    EvidenceSet,
    QueryHit,
    ScoredChunk,
    Subgraph,
    SubgraphEdge,
    SubgraphNode,
)
from provenance_service import create_app, tracer, validate_routes

from .clients import call
from .crew import run_crew
from .retrieval import RetrievalDeps, retrieve


async def _startup() -> None:
    validate_routes(["planner", "synthesizer", "critic"])  # fail fast on a route typo (M-14)


app = create_app("query-agent", on_startup=_startup)


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
    return list(resp.get("entity_ids", []))


async def _expand(entity_ids: list[str]) -> list[str]:
    out: list[str] = []
    for eid in entity_ids:
        resp = await call("graph", "/expand", {"entity_id": eid})
        out.extend(resp.get("entities", []))
    return out


def _deps() -> RetrievalDeps:
    return RetrievalDeps(embed=_embed, hybrid=_hybrid, rerank=_rerank, link=_link, expand=_expand)


def _scope(body: dict[str, object]) -> list[str]:
    """Normalize the request's KB scope: `kb_ids` list wins; else legacy `kb_id` → [kb_id]."""
    kb_ids = body.get("kb_ids")
    if isinstance(kb_ids, list) and kb_ids:
        return [str(k) for k in kb_ids]
    return [str(body.get("kb_id", "default"))]


@app.post("/retrieve", tags=["query"])
async def retrieve_endpoint(req: Request) -> dict[str, object]:
    """Resolve a query to an EvidenceSet via the retrieval core (R30)."""
    body = await req.json()
    query = body.get("query", "")
    kb_ids = _scope(body)
    with tracer("query-agent").start_as_current_span("query.retrieve") as span:
        evidence = await retrieve(query=query, kb_ids=kb_ids, deps=_deps(), k=int(body.get("k", 5)))
        span.set_attribute("retrieve.chunks", len(evidence.chunks))
        span.set_attribute("retrieve.graph_expanded", evidence.graph_expanded)
        return cast("dict[str, object]", evidence.model_dump())


@app.post("/answer", tags=["query"])
async def answer(req: Request) -> dict[str, object]:
    """Run the agentic crew: plan → retrieve → (synthesize → critique)* → cited Answer (R29–R33)."""
    body = await req.json()
    query = body.get("query", "")
    kb_ids = _scope(body)

    # Capture the evidence the crew actually retrieves so the caller doesn't retrieve a second
    # time, and so the returned evidence matches the answer's citations (R36, review M-15).
    # The closure captures the full KB scope so each subquery fans out over every selected KB
    # (R38); run_crew's per-subquery `kb` arg is informational — parity holds for a single KB.
    collected: list[EvidenceSet] = []

    async def _retrieve(kb: str, subquery: str) -> EvidenceSet:
        ev = await retrieve(query=subquery, kb_ids=kb_ids, deps=_deps())
        collected.append(ev)
        return ev

    with tracer("query-agent").start_as_current_span("query.answer") as span:
        ans = await run_crew(query, kb_ids[0], _retrieve, kb_ids=kb_ids)
        seen: set[str] = set()
        chunks: list[ScoredChunk] = []
        entity_ids: list[str] = []
        graph_expanded = False
        # Merge the per-subquery subgraphs so the UI EntityGraph sees one deduped graph (R37).
        nodes: list[SubgraphNode] = []
        edges: list[SubgraphEdge] = []
        seen_nodes: set[str] = set()
        seen_edges: set[tuple[str, str, str]] = set()
        for ev in collected:
            graph_expanded = graph_expanded or ev.graph_expanded
            for c in ev.chunks:
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    chunks.append(c)
            for e in ev.entity_ids:
                if e not in entity_ids:
                    entity_ids.append(e)
            for n in ev.subgraph.nodes:
                if n.id not in seen_nodes:
                    seen_nodes.add(n.id)
                    nodes.append(n)
            for edge in ev.subgraph.edges:
                key = (edge.src, edge.dst, edge.type)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(edge)
        evidence = EvidenceSet(
            subquery=query, chunks=chunks,
            entity_ids=entity_ids, graph_expanded=graph_expanded,
            subgraph=Subgraph(nodes=nodes, edges=edges),
        )
        span.set_attribute("answer.refused", ans.refused)
        span.set_attribute("answer.claims", len(ans.claims))
        return {
            "query": query,
            "answer": ans.model_dump(),
            "evidence": evidence.model_dump(),
        }
