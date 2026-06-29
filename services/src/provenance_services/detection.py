"""Domain detection (R8) + detect-but-confirm decision (R9/R55).

A real, runnable heuristic detector scores a document sample against each registered
domain's signal vocabulary (entity/relation types + description) and returns
{domain, confidence, rationale}. An LLM-based detector is the optional richer path
(used on the Spark); both route through the same code path (R49).
"""

from __future__ import annotations

import re

from provenance_contracts import GENERIC_FALLBACK_ID, REGISTRY, DomainSpec
from pydantic import BaseModel

# Below this top-score, we fall back to generic (R10).
MIN_SIGNAL_HITS = 2
# Below this confidence, the saga pauses for user confirmation (R9/R55).
AUTO_CONFIRM_THRESHOLD = 0.55

_TOKEN = re.compile(r"[a-z][a-z0-9]+")


class Detection(BaseModel):
    domain: str
    confidence: float
    rationale: str
    low_confidence: bool


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def _signals(spec: DomainSpec) -> set[str]:
    """Signal vocabulary for a domain: entity/relation type words + description words."""
    sig: set[str] = set()
    for t in spec.entity_types + spec.relation_types:
        sig.update(_TOKEN.findall(t.lower().replace("_", " ")))
    sig.update(_tokens(spec.description))
    # Drop generic stopword-ish tokens that don't discriminate.
    sig -= {"and", "the", "for", "with", "fallback", "out", "domain", "type", "open"}
    return sig


def detect(text: str, registry: dict[str, DomainSpec] | None = None) -> Detection:
    """Score the sample against each non-generic domain; fall back to generic."""
    reg = registry or REGISTRY
    doc = _tokens(text)
    scores: list[tuple[str, int, set[str]]] = []
    for spec in reg.values():
        if spec.id == GENERIC_FALLBACK_ID:
            continue
        hits = _signals(spec) & doc
        scores.append((spec.id, len(hits), hits))

    scores.sort(key=lambda s: s[1], reverse=True)
    top_id, top_hits, matched = scores[0]
    total = sum(s[1] for s in scores) or 1

    if top_hits < MIN_SIGNAL_HITS:
        return Detection(
            domain=GENERIC_FALLBACK_ID,
            confidence=0.0,
            rationale="no domain reached the minimum signal threshold",
            low_confidence=True,
        )

    confidence = top_hits / total
    return Detection(
        domain=top_id,
        confidence=round(confidence, 3),
        rationale=f"matched signals: {', '.join(sorted(matched))}",
        low_confidence=confidence < AUTO_CONFIRM_THRESHOLD,
    )


def should_pause_for_confirmation(d: Detection, threshold: float = AUTO_CONFIRM_THRESHOLD) -> bool:
    """detect-but-confirm (R9/R55): pause the saga when confidence is below threshold."""
    return d.confidence < threshold
