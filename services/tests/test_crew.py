"""Agentic crew tests (R29/R31/R32/R33/R65)."""

from __future__ import annotations

import pytest
from provenance_contracts import (
    Answer,
    BBox,
    Claim,
    CriticStatus,
    EvidenceSet,
    ScoredChunk,
    SubqueryType,
)
from provenance_services.crew import Critic, Planner, Synthesizer, run_crew


def _chunk(cid: str, text: str) -> ScoredChunk:
    return ScoredChunk(chunk_id=cid, text=text, page=1,
                       bbox=BBox(page=1, x0=0, y0=0, x1=1, y1=1), score=1.0)


def _evidence(query: str, chunks: list[ScoredChunk]) -> EvidenceSet:
    return EvidenceSet(subquery=query, chunks=chunks)


# ------------------------------------------------------------------- Planner (R29)
def test_planner_types_factual_relational_comparative() -> None:
    p = Planner()
    assert p.plan("what was the revenue", ["kb"]).subqueries[0].type is SubqueryType.FACTUAL
    assert p.plan("who audits Apple", ["kb"]).subqueries[0].type is SubqueryType.RELATIONAL

    comp = p.plan("risk factors in 2022 but not 2021", ["kb"])
    assert comp.synthesis_strategy == "set_difference"
    assert len(comp.subqueries) == 2
    assert all(s.type is SubqueryType.COMPARATIVE for s in comp.subqueries)


# --------------------------------------------------------------- Synthesizer (R33)
def test_synthesizer_builds_cited_claims() -> None:
    plan = Planner().plan("who is the auditor", ["kb"])
    ans = Synthesizer().synthesize(plan, [_evidence("q", [_chunk("c1", "the auditor is EY")])])
    assert ans.refused is False
    assert ans.claims and ans.claims[0].citations[0].chunk_id == "c1"


def test_synthesizer_relevance_gate_refuses_irrelevant_chunks() -> None:
    # A retrieved-but-irrelevant chunk yields an honest refusal, not a spurious answer.
    plan = Planner().plan("what is the CEO home address", ["kb"])
    ev = _evidence("q", [_chunk("c1", "the auditor is Ernst and Young")])
    assert Synthesizer().synthesize(plan, [ev]).refused is True


def test_synthesizer_set_difference_excludes_second_set() -> None:
    plan = Planner().plan("risk factors in 2022 but not 2021", ["kb"])
    ev_2022 = _evidence("2022", [_chunk("c1", "supply chain risk"), _chunk("c2", "fx risk")])
    ev_2021 = _evidence("2021", [_chunk("c2", "fx risk")])
    ans = Synthesizer().synthesize(plan, [ev_2022, ev_2021])
    ids = {c.citations[0].chunk_id for c in ans.claims}
    assert ids == {"c1"}  # c2 present in 2021 is excluded (set difference, R33)


def test_synthesizer_refuses_when_no_chunks() -> None:
    plan = Planner().plan("q", ["kb"])
    ans = Synthesizer().synthesize(plan, [_evidence("q", [])])
    assert ans.refused is True


# -------------------------------------------------------------------- Critic (R31)
def test_critic_ok_when_claims_grounded() -> None:
    ev = [_evidence("q", [_chunk("c1", "the independent auditor is Ernst and Young")])]
    ans = Answer(text="x", claims=[Claim(text="the independent auditor is Ernst and Young")])
    assert Critic().verify(ans, ev).status is CriticStatus.OK


def test_critic_revises_ungrounded_claim() -> None:
    ev = [_evidence("q", [_chunk("c1", "the auditor is Ernst and Young")])]
    ans = Answer(text="x", claims=[Claim(text="the company was founded on Mars in 1842")])
    v = Critic().verify(ans, ev)
    assert v.status is CriticStatus.REVISE
    assert v.ungrounded_claims == ["the company was founded on Mars in 1842"]


def test_critic_accepts_honest_refusal_as_absence() -> None:
    # A refusal grounded in an absence of evidence is correct, not a failure (R31).
    ans = Answer(text="not supported", refused=True)
    assert Critic().verify(ans, [_evidence("q", [])]).status is CriticStatus.OK


# ----------------------------------------------------------------- crew loop (R32)
@pytest.mark.asyncio
async def test_crew_happy_path_returns_grounded_cited_answer() -> None:
    async def retrieve(_kb: str, q: str) -> EvidenceSet:
        return _evidence(q, [_chunk("c1", "total revenue was 4.2 billion")])

    ans = await run_crew("what was revenue", "kb1", retrieve)
    assert ans.refused is False
    assert ans.claims[0].grounded is True
    assert ans.claims[0].citations[0].chunk_id == "c1"


@pytest.mark.asyncio
async def test_crew_honest_refusal_on_empty_corpus() -> None:
    async def retrieve(_kb: str, q: str) -> EvidenceSet:
        return _evidence(q, [])

    ans = await run_crew("anything", "kb1", retrieve)
    assert ans.refused is True and "not supported" in (ans.refusal_reason or "")


@pytest.mark.asyncio
async def test_crew_revises_then_succeeds() -> None:
    ev_chunk = _chunk("c1", "the auditor is Ernst and Young")

    async def retrieve(_kb: str, q: str) -> EvidenceSet:
        return _evidence(q, [ev_chunk])

    class FlakySynth(Synthesizer):
        def __init__(self) -> None:
            self.calls = 0

        def synthesize(self, plan, evidences, prev=None):  # type: ignore[no-untyped-def]
            self.calls += 1
            grounded = "the auditor is Ernst and Young"
            text = "made up fact about nothing" if self.calls == 1 else grounded
            return Answer(text=text, claims=[Claim(text=text)])

    ans = await run_crew("q", "kb1", retrieve, synthesizer=FlakySynth())
    assert ans.refused is False  # second (grounded) attempt accepted


@pytest.mark.asyncio
async def test_crew_strict_refusal_on_exhaustion() -> None:
    async def retrieve(_kb: str, q: str) -> EvidenceSet:
        return _evidence(q, [_chunk("c1", "the auditor is Ernst and Young")])

    class AlwaysUngrounded(Synthesizer):
        def synthesize(self, plan, evidences, prev=None):  # type: ignore[no-untyped-def]
            return Answer(text="fabricated", claims=[Claim(text="fabricated unrelated claim")])

    ans = await run_crew("q", "kb1", retrieve, synthesizer=AlwaysUngrounded(), max_iterations=2)
    assert ans.refused is True  # never releases ungrounded content (R32)
    assert "ungrounded" in (ans.refusal_reason or "")
