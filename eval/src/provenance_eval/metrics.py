"""Eval metrics + CI-gate thresholds (R41–R44, R71, §9.2).

Two tiers:
  * Computable offline (gated in CI): numeric exact-span (R42), domain-detection accuracy
    (R43), honest-refusal rate, answer-rate / over-refusal guard (R71), retrieval recall,
    and a groundedness proxy for faithfulness.
  * LLM-judged (gated on the Spark with a Claude judge): RAGAS faithfulness / answer
    relevancy / context precision+recall — interface present, reported `skipped` offline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from provenance_contracts import Answer


@dataclass(frozen=True)
class Threshold:
    target: float
    fail_below: float


# §9.2 — only the offline-computable metrics gate the build in CI.
THRESHOLDS: dict[str, Threshold] = {
    "numeric_exactness": Threshold(1.00, 1.00),
    "detection_accuracy": Threshold(0.90, 0.85),
    "honest_refusal_rate": Threshold(0.95, 0.90),
    "answer_rate": Threshold(0.90, 0.85),
    "retrieval_recall": Threshold(0.80, 0.80),
    "groundedness": Threshold(0.90, 0.85),
}


# Groundedness is scored against the source corpus, not the system's own verdict — a
# containment floor below which a released sentence is treated as unfaithful (review C-2).
_GROUNDING_CONTAINMENT = 0.6
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for", "and",
    "or", "what", "who", "which", "when", "where", "how", "does", "did", "do", "that",
    "this", "with", "by", "at", "as", "it", "its", "be", "been", "has", "have", "had",
}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def _norm_num(s: str) -> str:
    return re.sub(r"[,$\s]", "", s).lower()


def numeric_exact_match(expected: str, answer: Answer) -> bool:
    """R42: the expected numeric span appears verbatim (normalized) in the answer."""
    if answer.refused:
        return False
    return _norm_num(expected) in _norm_num(answer.text)


def rate(flags: list[bool]) -> float:
    return sum(flags) / len(flags) if flags else 0.0


def _sentence_supported(sentence: str, corpus_tokens: set[str]) -> bool:
    """A released sentence is faithful if its salient tokens are lexically present in the
    source corpus. Offline stand-in for RAGAS faithfulness (§9.2, R41)."""
    salient = _tokens(sentence) - _STOPWORDS
    if not salient:
        return True  # no content-bearing tokens (boilerplate) ⇒ nothing to fabricate
    return len(salient & corpus_tokens) / len(salient) >= _GROUNDING_CONTAINMENT


def groundedness(answers: list[Answer], corpus_text: str) -> float:
    """Faithfulness proxy independent of the system's self-report (review C-2).

    Scores released answer sentences against the *ingested corpus* — a signal the system
    does not control — instead of the Critic's own grounded flag (which run_crew sets to
    True on every released claim, making the old metric a structural constant of 1.0).
    """
    corpus_tokens = _tokens(corpus_text)
    sentences = [s for a in answers if not a.refused for s in _sentences(a.text)]
    if not sentences:
        return 1.0  # nothing released ⇒ nothing unfaithful
    return rate([_sentence_supported(s, corpus_tokens) for s in sentences])


# ---- LLM-judged RAGAS metrics (interface only; computed on the Spark) ----
class LLMJudge:
    """Marker for the Claude-backed judge used by the full RAGAS metrics on the Spark."""


def ragas_faithfulness(judge: LLMJudge | None, *_args: object) -> float | None:
    if judge is None:
        return None  # skipped offline — gated on the Spark
    raise NotImplementedError("LLM-judged faithfulness runs on the Spark (P4-full)")
