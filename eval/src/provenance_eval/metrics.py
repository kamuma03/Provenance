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


def _norm_num(s: str) -> str:
    return re.sub(r"[,$\s]", "", s).lower()


def numeric_exact_match(expected: str, answer: Answer) -> bool:
    """R42: the expected numeric span appears verbatim (normalized) in the answer."""
    if answer.refused:
        return False
    return _norm_num(expected) in _norm_num(answer.text)


def rate(flags: list[bool]) -> float:
    return sum(flags) / len(flags) if flags else 0.0


def groundedness(answers: list[Answer]) -> float:
    """Faithfulness proxy: fraction of released claims marked grounded by the Critic."""
    claims = [c for a in answers if not a.refused for c in a.claims]
    if not claims:
        return 1.0  # nothing released ⇒ nothing unfaithful
    return rate([bool(c.grounded) for c in claims])


# ---- LLM-judged RAGAS metrics (interface only; computed on the Spark) ----
class LLMJudge:
    """Marker for the Claude-backed judge used by the full RAGAS metrics on the Spark."""


def ragas_faithfulness(judge: LLMJudge | None, *_args: object) -> float | None:
    if judge is None:
        return None  # skipped offline — gated on the Spark
    raise NotImplementedError("LLM-judged faithfulness runs on the Spark (P4-full)")
