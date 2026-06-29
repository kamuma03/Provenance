"""Retrieval core (R24–R28) — the clean query() API independent of the agent layer.

Pipeline: embed → hybrid (dense + BM25) → cross-encoder rerank → additive graph lift.
**Vector is the floor; graph is the lift** (R25): chunks always come from hybrid+rerank;
graph linking/expansion only *adds* entity context. The empty-expansion ladder (R27)
degrades gracefully — no linked entities ⇒ vector evidence stands, never graph-only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from provenance_contracts import BBox, EvidenceSet, QueryHit, ScoredChunk

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


def _to_chunk(h: QueryHit) -> ScoredChunk:
    page = int(h.metadata.get("page", "0") or 0)
    raw = h.metadata.get("bbox")
    bbox = BBox.model_validate_json(raw) if raw else BBox(page=page, x0=0, y0=0, x1=0, y1=0)
    return ScoredChunk(chunk_id=h.chunk_id, text=h.text, page=page, bbox=bbox, score=h.score)


async def retrieve(kb_id: str, query: str, deps: RetrievalDeps, k: int = 5) -> EvidenceSet:
    """Resolve a query to an EvidenceSet (R30). Vector floor + additive graph lift (R25)."""
    vector = await deps.embed(query)
    hits = await deps.hybrid(kb_id, vector, query, k * 3) if vector else []
    reranked = await deps.rerank(query, hits) if hits else []
    top = reranked[:k]

    # Additive graph lift; empty-expansion ladder governs the entity side (R27).
    linked = await deps.link(kb_id, query)
    expanded = await deps.expand(linked) if linked else []
    entity_ids = list(dict.fromkeys([*linked, *expanded]))

    return EvidenceSet(
        subquery=query,
        chunks=[_to_chunk(h) for h in top],
        entity_ids=entity_ids,
        graph_expanded=bool(linked),
    )
