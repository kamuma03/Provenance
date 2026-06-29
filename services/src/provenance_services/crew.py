"""Agentic crew (R29–R33, R65) — Planner → Retriever → Critic → Synthesizer.

Offline-runnable heuristic implementations with an optional LLMClient for the richer
Claude path (the Retriever is the P2 retrieval core). The orchestration enforces:
  - claim-level groundedness with **strict whole-answer refusal** (R31/R32/R65)
  - a hard MAX_ITERATIONS bound (R32)
  - the comparative set-difference compare-op (R33)
  - the Critic distinguishes an *ungrounded claim* from a *correctly-grounded absence* (R31)
"""

from __future__ import annotations

import os
import re
from collections.abc import Awaitable, Callable

from provenance_contracts import (
    Answer,
    Citation,
    Claim,
    CriticStatus,
    EvidenceSet,
    Plan,
    ScoredChunk,
    Subquery,
    SubqueryType,
    Verdict,
)

MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "3"))  # hard loop bound (R32)
GROUNDING_THRESHOLD = 0.6  # fraction of claim tokens that must appear in some evidence chunk

_COMPARATIVE = ("but not", "compared to", " versus ", " vs ", "difference between")
_RELATIONAL = ("related to", "connected", "associated with", "owns", "subsidiar", "auditor of",
               "who audits", "parties to")
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for", "and",
    "or", "what", "who", "which", "when", "where", "how", "does", "did", "do", "that",
    "this", "with", "by", "at", "as", "personal",
}

RetrieveFn = Callable[[str, str], Awaitable[EvidenceSet]]  # (kb_id, subquery) -> EvidenceSet


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


# --------------------------------------------------------------------------- Planner
class Planner:
    """Query → Plan: decompose, scope KB, type each subquery (R29)."""

    def plan(self, query: str, kb_scope: list[str]) -> Plan:
        ql = query.lower()
        if any(m in ql for m in _COMPARATIVE):
            split = re.split(r"but not|compared to|versus|\bvs\b", ql)
            parts = [p.strip() for p in split if p.strip()]
            subs = [Subquery(text=p, type=SubqueryType.COMPARATIVE) for p in parts[:2]]
            if len(subs) < 2:
                subs = [Subquery(text=query, type=SubqueryType.COMPARATIVE)]
            return Plan(kb_scope=kb_scope, subqueries=subs, synthesis_strategy="set_difference")
        is_rel = any(m in ql for m in _RELATIONAL)
        qtype = SubqueryType.RELATIONAL if is_rel else SubqueryType.FACTUAL
        return Plan(kb_scope=kb_scope, subqueries=[Subquery(text=query, type=qtype)],
                    synthesis_strategy="direct")


# ----------------------------------------------------------------------- Synthesizer
class Synthesizer:
    """Compose a cited Answer from evidence; execute the compare-op for comparative (R33)."""

    def synthesize(
        self, plan: Plan, evidences: list[EvidenceSet], prev: Verdict | None = None
    ) -> Answer:
        chunks = self._select_chunks(plan, evidences)
        if not chunks:
            return Answer(
                text="The documents do not support an answer to this question.",
                refused=True,
                refusal_reason="not supported by the corpus",
            )
        claims = [
            Claim(
                text=c.text,
                citations=[Citation(chunk_id=c.chunk_id, page=c.page, bbox=c.bbox)],
            )
            for c in chunks
        ]
        return Answer(text=" ".join(c.text for c in claims), claims=claims)

    def _select_chunks(self, plan: Plan, evidences: list[EvidenceSet]) -> list[ScoredChunk]:
        if plan.synthesis_strategy == "set_difference" and len(evidences) >= 2:
            # Comparative: chunks in the first set but NOT the second (R33).
            exclude = {c.chunk_id for c in evidences[1].chunks}
            candidates = [c for c in evidences[0].chunks if c.chunk_id not in exclude]
        else:
            seen: set[str] = set()
            candidates = []
            for ev in evidences:
                for c in ev.chunks:
                    if c.chunk_id not in seen:
                        seen.add(c.chunk_id)
                        candidates.append(c)
        # Relevance gate (offline proxy): keep only chunks sharing a salient term with the
        # query, so irrelevant-but-retrieved chunks yield an honest refusal rather than a
        # spurious answer. The LLM synthesizer refines relevance/refusal on the Spark.
        qterms = {t for sq in plan.subqueries for t in _tokens(sq.text)} - _STOPWORDS
        if qterms:
            candidates = [c for c in candidates if qterms & _tokens(c.text)]
        return candidates[:5]


# ----------------------------------------------------------------------------- Critic
class Critic:
    """Verify groundedness claim-by-claim; strict whole-answer refusal (R31/R65)."""

    def verify(self, answer: Answer, evidences: list[EvidenceSet]) -> Verdict:
        # An honest refusal grounded in an *absence* of evidence is correct (R31).
        if answer.refused:
            return Verdict(status=CriticStatus.OK)
        chunk_tokens = [_tokens(c.text) for ev in evidences for c in ev.chunks]
        ungrounded: list[str] = []
        for claim in answer.claims:
            if not self._grounded(claim.text, chunk_tokens):
                ungrounded.append(claim.text)
        if ungrounded:
            return Verdict(status=CriticStatus.REVISE, ungrounded_claims=ungrounded)
        return Verdict(status=CriticStatus.OK)

    def _grounded(self, text: str, chunk_tokens: list[set[str]]) -> bool:
        ct = _tokens(text)
        if not ct:
            return False
        return any(len(ct & toks) / len(ct) >= GROUNDING_THRESHOLD for toks in chunk_tokens)


# ------------------------------------------------------------------------ orchestration
async def run_crew(
    query: str,
    kb_id: str,
    retrieve_fn: RetrieveFn,
    *,
    planner: Planner | None = None,
    synthesizer: Synthesizer | None = None,
    critic: Critic | None = None,
    max_iterations: int = MAX_ITERATIONS,
) -> Answer:
    """Plan → retrieve → (synthesize → critique)* with a hard iteration bound (R32)."""
    planner = planner or Planner()
    synthesizer = synthesizer or Synthesizer()
    critic = critic or Critic()

    plan = planner.plan(query, [kb_id])
    evidences = [await retrieve_fn(kb_id, sq.text) for sq in plan.subqueries]

    verdict: Verdict | None = None
    for _ in range(max_iterations):
        answer = synthesizer.synthesize(plan, evidences, verdict)
        if answer.refused:
            return answer  # honest refusal (absence) — Critic confirms this is OK
        verdict = critic.verify(answer, evidences)
        if verdict.status is CriticStatus.OK:
            for claim in answer.claims:
                claim.grounded = True
            return answer

    # Strict whole-answer refusal on exhaustion (R32): never release ungrounded content.
    return Answer(
        text="Unable to produce a fully grounded answer.",
        refused=True,
        refusal_reason=f"claims remained ungrounded after {max_iterations} iterations",
    )
