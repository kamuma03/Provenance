"""Retrieval core tests (R25/R27/R28/R30) — injected fakes, no live services."""

from __future__ import annotations

import pytest
from provenance_contracts import BBox, QueryHit
from provenance_services.retrieval import RetrievalDeps, retrieve


def _hit(cid: str, text: str, score: float) -> QueryHit:
    meta = {"page": "1", "bbox": BBox(page=1, x0=0, y0=0, x1=1, y1=1).model_dump_json()}
    return QueryHit(chunk_id=cid, score=score, text=text, metadata=meta)


def _deps(*, hits, linked, expanded, rerank=None) -> RetrievalDeps:
    async def embed(_q):
        return [0.1, 0.2, 0.3]

    async def hybrid(_kb, _v, _t, _k):
        return list(hits)

    async def do_rerank(_q, hs):
        return rerank(hs) if rerank else hs

    async def link(_kb, _t):
        return list(linked)

    async def expand(ids):
        return list(expanded) if ids else []

    return RetrievalDeps(embed=embed, hybrid=hybrid, rerank=do_rerank, link=link, expand=expand)


@pytest.mark.asyncio
async def test_normal_retrieval_with_graph_lift() -> None:
    hits = [_hit("c1", "alpha", 0.9), _hit("c2", "beta", 0.5)]
    ev = await retrieve("kb1", "q", _deps(hits=hits, linked=["e1"], expanded=["e2"]), k=5)
    assert [c.chunk_id for c in ev.chunks] == ["c1", "c2"]
    assert ev.chunks[0].bbox.page == 1  # geometry carried for citations
    assert ev.entity_ids == ["e1", "e2"]  # linked + expanded
    assert ev.graph_expanded is True


@pytest.mark.asyncio
async def test_rerank_reorders_chunks() -> None:
    hits = [_hit("c1", "alpha", 0.9), _hit("c2", "beta", 0.5)]
    ev = await retrieve(
        "kb1", "q", _deps(hits=hits, linked=[], expanded=[], rerank=lambda hs: list(reversed(hs)))
    )
    assert [c.chunk_id for c in ev.chunks] == ["c2", "c1"]  # rerank order wins


@pytest.mark.asyncio
async def test_empty_expansion_ladder_keeps_vector_floor() -> None:
    # No linked entities => graph lift is empty, but vector chunks still stand (R25/R27).
    hits = [_hit("c1", "alpha", 0.9)]
    ev = await retrieve("kb1", "q", _deps(hits=hits, linked=[], expanded=["should-be-ignored"]))
    assert [c.chunk_id for c in ev.chunks] == ["c1"]
    assert ev.entity_ids == []  # expand not called when nothing linked
    assert ev.graph_expanded is False


@pytest.mark.asyncio
async def test_empty_corpus_yields_empty_evidence() -> None:
    ev = await retrieve("kb1", "q", _deps(hits=[], linked=[], expanded=[]))
    assert ev.chunks == []
    assert ev.graph_expanded is False  # honest: nothing retrieved, nothing fabricated


@pytest.mark.asyncio
async def test_graph_outage_degrades_to_vector_floor() -> None:
    # A Graph-service failure must not fail the query — vector evidence still stands (H-6).
    hits = [_hit("c1", "alpha", 0.9)]
    deps = _deps(hits=hits, linked=[], expanded=[])

    async def boom(_kb, _t):
        raise RuntimeError("graph down")

    deps.link = boom
    ev = await retrieve("kb1", "q", deps)
    assert [c.chunk_id for c in ev.chunks] == ["c1"]
    assert ev.entity_ids == []
    assert ev.graph_expanded is False


@pytest.mark.asyncio
async def test_rerank_failure_keeps_hybrid_hits() -> None:
    # A rerank failure must keep the hybrid fusion order, not discard the hits (H-6).
    hits = [_hit("c1", "alpha", 0.9), _hit("c2", "beta", 0.5)]
    deps = _deps(hits=hits, linked=[], expanded=[])

    async def boom(_q, _hits):
        raise RuntimeError("reranker down")

    deps.rerank = boom
    ev = await retrieve("kb1", "q", deps)
    assert [c.chunk_id for c in ev.chunks] == ["c1", "c2"]  # hybrid order preserved
