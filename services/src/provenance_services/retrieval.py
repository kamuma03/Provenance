"""Retrieval core (R24–R28) — the clean query() API independent of the agent layer.

Pipeline: embed → hybrid (dense + BM25) → cross-encoder rerank → additive graph lift.
**Vector is the floor; graph is the lift** (R25): chunks always come from hybrid+rerank;
graph linking/expansion only *adds* entity context. The empty-expansion ladder (R27)
degrades gracefully — no linked entities ⇒ vector evidence stands, never graph-only.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from opentelemetry import trace
from provenance_contracts import (
    BBox,
    EvidenceSet,
    QueryHit,
    ScoredChunk,
    Subgraph,
    SubgraphEdge,
    SubgraphNode,
)

log = logging.getLogger("retrieval")

EmbedFn = Callable[[str], Awaitable[list[float]]]
HybridFn = Callable[[str, list[float], str, int], Awaitable[list[QueryHit]]]
RerankFn = Callable[[str, list[QueryHit]], Awaitable[list[QueryHit]]]
LinkFn = Callable[[str, str], Awaitable[list[str]]]
ExpandFn = Callable[[list[str]], Awaitable[list[str]]]


@dataclass
class RetrievalDeps:
    embed: EmbedFn
    hybrid: HybridFn
    rerank: RerankFn
    link: LinkFn
    expand: ExpandFn


def _build_subgraph(linked: list[str], expanded: list[str]) -> Subgraph:
    """Assemble the per-answer subgraph the UI renders (R37/R-BE-9) from the graph lift.

    Nodes are the linked (query-matched) and graph-expanded entities; edges record the real
    provenance relation — each expanded entity was reached *by expanding from* the linked set.
    Names fall back to the entity id here because the retrieval layer only receives ids; the
    Graph service returning canonical names + entity types + relation labels is a tracked
    follow-up (see todo.md T19/T20). The structure is stable either way."""
    nodes: list[SubgraphNode] = []
    seen: set[str] = set()
    for eid in linked:
        if eid not in seen:
            seen.add(eid)
            nodes.append(SubgraphNode(id=eid, name=eid, type="entity"))
    for eid in expanded:
        if eid not in seen:
            seen.add(eid)
            nodes.append(SubgraphNode(id=eid, name=eid, type="entity"))
    edges = [
        SubgraphEdge(src=src, dst=dst, type="expands_to")
        for src in linked
        for dst in expanded
        if src != dst
    ]
    return Subgraph(nodes=nodes, edges=edges)


def _to_chunk(h: QueryHit) -> ScoredChunk:
    page = int(h.metadata.get("page", "0") or 0)
    raw = h.metadata.get("bbox")
    # BBox.model_validate_json preserves page_width/page_height carried from parse (L-10).
    bbox = BBox.model_validate_json(raw) if raw else BBox(page=page, x0=0, y0=0, x1=0, y1=0)
    return ScoredChunk(chunk_id=h.chunk_id, text=h.text, page=page, bbox=bbox, score=h.score)


async def retrieve(
    kb_id: str | None = None,
    query: str = "",
    deps: RetrievalDeps | None = None,
    k: int = 5,
    *,
    kb_ids: list[str] | None = None,
) -> EvidenceSet:
    """Resolve a query to an EvidenceSet (R30). Vector floor + additive graph lift (R25).

    Accepts either a single ``kb_id`` (legacy) or a ``kb_ids`` list (multi-KB, R38). The two
    forms are unified through ``scope``: **``kb_ids=[x]`` is byte-identical to ``kb_id=x``**
    (fan-out over one KB is just that KB), which protects the eval gate (core constraint #1).
    Across several KBs the hits and linked entities are unioned in KB order, deduped by id.
    """
    if deps is None:  # deps is positional-3 for the legacy form; guard the keyword form
        raise ValueError("retrieve requires deps")
    scope = kb_ids if kb_ids is not None else ([kb_id] if kb_id is not None else [])
    span = trace.get_current_span()
    vector = await deps.embed(query)

    # Vector floor fanned out across the selected KBs, unioned in scope order and deduped by
    # chunk_id (globally unique) — for a single KB this is exactly the legacy hit list (parity).
    hits: list[QueryHit] = []
    if vector:
        seen_hits: set[str] = set()
        for kb in scope:
            for h in await deps.hybrid(kb, vector, query, k * 3):
                if h.chunk_id not in seen_hits:
                    seen_hits.add(h.chunk_id)
                    hits.append(h)

    # Rerank is a refinement, not the floor: a Model-service hiccup must not throw away good
    # hybrid hits — fall back to the hybrid fusion order (R25, review H-6).
    try:
        reranked = await deps.rerank(query, hits) if hits else []
    except Exception as exc:
        log.warning("rerank failed; keeping hybrid order: %s", exc)
        span.set_attribute("retrieval.rerank_failed", True)
        reranked = hits
    top = reranked[:k]

    # Additive graph lift; empty-expansion ladder governs the entity side (R27). A Graph-
    # service outage degrades to vector-only evidence — never fails the whole query (R25/H-6).
    try:
        linked = []
        for kb in scope:
            for e in await deps.link(kb, query):
                if e not in linked:
                    linked.append(e)
        expanded = await deps.expand(linked) if linked else []
    except Exception as exc:
        log.warning("graph lift failed; vector floor stands: %s", exc)
        span.set_attribute("retrieval.graph_failed", True)
        linked, expanded = [], []
    entity_ids = list(dict.fromkeys([*linked, *expanded]))

    return EvidenceSet(
        subquery=query,
        chunks=[_to_chunk(h) for h in top],
        entity_ids=entity_ids,
        graph_expanded=bool(linked),
        subgraph=_build_subgraph(linked, expanded),
    )
