"""Agentic crew (R29–R33, R65) — Planner → Retriever → Critic → Synthesizer.

Each agent takes an optional LLMClient (resolved per task by the router, A2). With none it
runs deterministic heuristics (offline-safe); with one it uses the LLM. The orchestration
enforces:
  - claim-level groundedness with **strict whole-answer refusal** (R31/R32/R65)
  - a hard MAX_ITERATIONS bound (R32)
  - the comparative set-difference compare-op (R33)
  - the Critic distinguishes an *ungrounded claim* from a *correctly-grounded absence* (R31)
"""

from __future__ import annotations

import json
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
from provenance_service import LLMClient, get_llm

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


def _sentences(text: str) -> list[str]:
    """Atomic-claim split of an answer (R65): sentence granularity is the floor."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def _cite_for(sentence: str, chunks: list[ScoredChunk]) -> list[Citation]:
    """Attach the best-overlapping evidence chunk as this sentence's span citation.

    Span-level provenance (R36/R65): a released sentence points at the chunk it is most
    grounded in. No overlap ⇒ no citation, and the Critic will flag it ungrounded.
    """
    st = _tokens(sentence)
    if not st:
        return []
    best: ScoredChunk | None = None
    best_overlap = 0.0
    for c in chunks:
        overlap = len(st & _tokens(c.text)) / len(st)
        if overlap > best_overlap:
            best, best_overlap = c, overlap
    if best is None or best_overlap == 0.0:
        return []
    return [Citation(chunk_id=best.chunk_id, page=best.page, bbox=best.bbox)]


# --------------------------------------------------------------------------- Planner
class Planner:
    """Query → Plan: decompose, scope KB, type each subquery (R29)."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm

    async def plan(self, query: str, kb_scope: list[str]) -> Plan:
        if self._llm is not None:
            llm_plan = await self._llm_plan(query, kb_scope)
            if llm_plan is not None:
                return llm_plan
        return self._heuristic_plan(query, kb_scope)

    def _heuristic_plan(self, query: str, kb_scope: list[str]) -> Plan:
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

    async def _llm_plan(self, query: str, kb_scope: list[str]) -> Plan | None:
        system = (
            "Decompose the user's question into 1-2 search subqueries. Classify each as "
            "factual | relational | comparative. Reply with JSON only: "
            '{"subqueries": [{"text": "...", "type": "..."}], '
            '"synthesis_strategy": "direct|set_difference"}.'
        )
        try:
            raw = await self._llm.complete(system, query)  # type: ignore[union-attr]
            data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
            subs = [
                Subquery(text=s["text"], type=SubqueryType(s["type"]))
                for s in data["subqueries"]
            ][:2]
            if not subs:
                return None
            return Plan(kb_scope=kb_scope, subqueries=subs,
                        synthesis_strategy=data.get("synthesis_strategy", "direct"))
        except Exception:
            return None  # malformed → heuristic fallback


# ----------------------------------------------------------------------- Synthesizer
class Synthesizer:
    """Compose a cited Answer from evidence; execute the compare-op for comparative (R33)."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm

    async def synthesize(
        self, plan: Plan, evidences: list[EvidenceSet], prev: Verdict | None = None
    ) -> Answer:
        chunks = self._select_chunks(plan, evidences)
        if not chunks:
            return Answer(
                text="The documents do not support an answer to this question.",
                refused=True,
                refusal_reason="not supported by the corpus",
            )
        # Extractive default: claims are chunk-derived, grounded by construction (R65).
        claims = [
            Claim(text=c.text, citations=[Citation(chunk_id=c.chunk_id, page=c.page, bbox=c.bbox)])
            for c in chunks
        ]
        text = " ".join(c.text for c in claims)
        if self._llm is not None:
            llm_text = await self._llm_text(plan, chunks)
            if llm_text:
                # The user reads the LLM prose, so the Critic must verify *that* — not the
                # chunk echoes above. Decompose the released text into atomic claims and cite
                # each from the evidence, so groundedness is checked on what is actually shown
                # and span provenance maps to released sentences (R65/R36, review C-1).
                text = llm_text
                decomposed = [
                    Claim(text=s, citations=_cite_for(s, chunks)) for s in _sentences(llm_text)
                ]
                claims = decomposed or claims
        return Answer(text=text, claims=claims)

    async def _llm_text(self, plan: Plan, chunks: list[ScoredChunk]) -> str | None:
        system = (
            "Answer the question using ONLY the evidence provided. Be concise. Do not add "
            "facts that are not in the evidence."
        )
        question = " ".join(sq.text for sq in plan.subqueries)
        evidence = "\n".join(f"- {c.text}" for c in chunks)
        try:
            return await self._llm.complete(  # type: ignore[union-attr]
                system, f"Question: {question}\n\nEvidence:\n{evidence}"
            )
        except Exception:
            return None  # fall back to the extractive text

    def _select_chunks(self, plan: Plan, evidences: list[EvidenceSet]) -> list[ScoredChunk]:
        if plan.synthesis_strategy == "set_difference" and len(evidences) >= 2:
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

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm

    async def verify(self, answer: Answer, evidences: list[EvidenceSet]) -> Verdict:
        # An honest refusal grounded in an *absence* of evidence is correct (R31).
        if answer.refused:
            return Verdict(status=CriticStatus.OK)
        evidence_text = "\n".join(c.text for ev in evidences for c in ev.chunks)
        chunk_tokens = [_tokens(c.text) for ev in evidences for c in ev.chunks]
        ungrounded: list[str] = []
        for claim in answer.claims:
            grounded = (
                await self._llm_grounded(claim.text, evidence_text)
                if self._llm is not None
                else self._grounded(claim.text, chunk_tokens)
            )
            if not grounded:
                ungrounded.append(claim.text)
        if ungrounded:
            return Verdict(status=CriticStatus.REVISE, ungrounded_claims=ungrounded)
        return Verdict(status=CriticStatus.OK)

    def _grounded(self, text: str, chunk_tokens: list[set[str]]) -> bool:
        ct = _tokens(text)
        if not ct:
            return False
        return any(len(ct & toks) / len(ct) >= GROUNDING_THRESHOLD for toks in chunk_tokens)

    async def _llm_grounded(self, claim: str, evidence: str) -> bool:
        system = (
            "You verify whether a claim is fully supported by the evidence. "
            "Reply with exactly YES or NO."
        )
        try:
            out = await self._llm.complete(  # type: ignore[union-attr]
                system, f"Evidence:\n{evidence}\n\nClaim: {claim}"
            )
            return out.strip().upper().startswith("YES")
        except Exception:
            # Fail closed: a judge failure must not silently pass a claim through the release
            # gate. Ungrounded ⇒ REVISE ⇒ honest refusal on exhaustion (R31/R32, review C-1).
            return False


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
    """Plan → retrieve → (synthesize → critique)* with a hard iteration bound (R32).

    Each agent is resolved from the per-task LLM router unless explicitly injected (A2).
    """
    planner = planner or Planner(get_llm("planner"))
    synthesizer = synthesizer or Synthesizer(get_llm("synthesizer"))
    critic = critic or Critic(get_llm("critic"))

    plan = await planner.plan(query, [kb_id])
    evidences = [await retrieve_fn(kb_id, sq.text) for sq in plan.subqueries]

    verdict: Verdict | None = None
    for _ in range(max_iterations):
        answer = await synthesizer.synthesize(plan, evidences, verdict)
        if answer.refused:
            return answer  # honest refusal (absence) — Critic confirms this is OK
        verdict = await critic.verify(answer, evidences)
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
