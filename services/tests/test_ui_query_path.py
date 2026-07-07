"""Pre-implementation (RED) tests for the UI-redesign query path.

Maps to spec.md: R-BE-2 (multi-KB), R-BE-3 (Critic verdict surfaced),
R-BE-9 (per-answer subgraph). Offline, injected-fakes style — matches
test_retrieval.py / test_crew.py. These FAIL until the features exist.
"""

from __future__ import annotations

import pytest
from provenance_contracts import Answer, BBox, Claim, EvidenceSet, QueryHit, ScoredChunk
from provenance_services.crew import Synthesizer, run_crew
from provenance_services.retrieval import RetrievalDeps, retrieve


# ----------------------------------------------------------------- helpers (copied style)
def _hit(cid: str, text: str, score: float) -> QueryHit:
    meta = {"page": "1", "bbox": BBox(page=1, x0=0, y0=0, x1=1, y1=1).model_dump_json()}
    return QueryHit(chunk_id=cid, score=score, text=text, metadata=meta)


def _deps(*, per_kb_hits, linked, expanded):  # type: ignore[no-untyped-def]
    async def embed(_q):
        return [0.1, 0.2, 0.3]

    async def hybrid(kb, _v, _t, _k):
        return list(per_kb_hits.get(kb, []))

    async def do_rerank(_q, hs):
        return hs

    async def link(_kb, _t):
        return list(linked)

    async def expand(ids):
        return list(expanded) if ids else []

    return RetrievalDeps(embed=embed, hybrid=hybrid, rerank=do_rerank, link=link, expand=expand)


def _chunk(cid: str, text: str) -> ScoredChunk:
    return ScoredChunk(chunk_id=cid, text=text, page=1,
                       bbox=BBox(page=1, x0=0, y0=0, x1=1, y1=1), score=1.0)


def _evidence(query: str, chunks: list[ScoredChunk]) -> EvidenceSet:
    return EvidenceSet(subquery=query, chunks=chunks)


# --------------------------------------------------------- R-BE-2 · multi-KB query path
@pytest.mark.asyncio
async def test_retrieve_kb_ids_singleton_is_byte_identical_to_kb_id() -> None:
    """kb_ids=[x] must produce the exact same EvidenceSet as the legacy kb_id=x path
    (protects the eval gate — core constraint #1)."""
    deps = _deps(per_kb_hits={"kb1": [_hit("c1", "alpha", 0.9)]}, linked=["e1"], expanded=["e2"])
    single = await retrieve("kb1", "q", deps)
    multi = await retrieve(query="q", kb_ids=["kb1"], deps=deps)  # NEW signature — red until added
    assert multi.model_dump() == single.model_dump()


@pytest.mark.asyncio
async def test_retrieve_fans_out_and_unions_across_kbs() -> None:
    """A cross-KB query retrieves from every selected KB and unions the evidence (R38)."""
    deps = _deps(
        per_kb_hits={"kbA": [_hit("a1", "alpha", 0.9)], "kbB": [_hit("b1", "beta", 0.8)]},
        linked=[], expanded=[],
    )
    ev = await retrieve(query="q", kb_ids=["kbA", "kbB"], deps=deps)
    assert {c.chunk_id for c in ev.chunks} == {"a1", "b1"}


# --------------------------------------------------- R-BE-3 · Critic verdict surfaced
@pytest.mark.asyncio
async def test_refusal_answer_exposes_ungrounded_claims_and_no_citation() -> None:
    """On strict-refusal exhaustion the Answer must carry the specific ungrounded claim(s)
    the Critic rejected, and fabricate no citation (R31/R32; feeds the refusal card)."""

    async def _retrieve(_kb: str, q: str) -> EvidenceSet:
        return _evidence(q, [_chunk("c1", "the auditor is Ernst and Young")])

    class AlwaysUngrounded(Synthesizer):
        async def synthesize(self, plan, evidences, prev=None):  # type: ignore[no-untyped-def]
            return Answer(text="fabricated", claims=[Claim(text="fabricated unrelated claim")])

    ans = await run_crew("q", "kb1", _retrieve, synthesizer=AlwaysUngrounded(), max_iterations=2)
    assert ans.refused is True
    # NEW field on Answer — AttributeError (red) until the contract + crew expose it.
    assert ans.ungrounded_claims == ["fabricated unrelated claim"]
    assert all(not c.citations for c in ans.claims)  # no fabricated citation


# ------------------------------------------------------- R-BE-9 · per-answer subgraph
def test_evidenceset_has_subgraph_with_nodes_and_edges() -> None:
    """EvidenceSet gains an additive `subgraph{nodes[{id,name,type}], edges[{src,dst,type}]}`."""
    ev = EvidenceSet(subquery="q")
    assert hasattr(ev, "subgraph")  # red until the contract field is added
    assert ev.subgraph.nodes == []
    assert ev.subgraph.edges == []


@pytest.mark.asyncio
async def test_retrieve_populates_named_typed_subgraph_when_graph_expands() -> None:
    """When the graph lift links entities, the evidence carries a named/typed subgraph the
    UI can render as nodes + edges (R37) — not just raw ids."""
    deps = _deps(per_kb_hits={"kb1": [_hit("c1", "alpha", 0.9)]}, linked=["e1"], expanded=["e2"])
    ev = await retrieve("kb1", "q", deps)
    names = {n.name for n in ev.subgraph.nodes}  # red until subgraph exists + is populated
    assert names and all(n.type for n in ev.subgraph.nodes)
    assert ev.subgraph.edges  # at least one relation between linked/expanded entities
