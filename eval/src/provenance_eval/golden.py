"""Golden-set schema + loader (R40 seed).

The golden set drives the P4 eval gate (RAGAS faithfulness, numeric exactness, multi-hop
correctness, domain-detection accuracy, honest-refusal, over-refusal — §9.2). P1 seeds a
small validated set; it grows as real corpora are ingested.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Cohort(StrEnum):
    TEXTUAL_FACTUAL = "textual_factual"
    NUMERIC_FACTUAL = "numeric_factual"
    RELATIONAL = "relational"
    OUT_OF_CORPUS = "out_of_corpus"
    ANSWERABLE = "answerable"
    DOMAIN_DETECTION = "domain_detection"


class SourceSpan(BaseModel):
    document: str
    page: int | None = None
    quote: str | None = None  # the span the answer must be grounded in


class GoldenItem(BaseModel):
    id: str
    cohort: Cohort
    domain: str
    question: str
    expected: str
    answerable: bool = True
    source: SourceSpan | None = None


class GoldenSet(BaseModel):
    items: list[GoldenItem] = Field(default_factory=list)

    def by_cohort(self, cohort: Cohort) -> list[GoldenItem]:
        return [i for i in self.items if i.cohort is cohort]


def load_golden(path: str | Path) -> GoldenSet:
    data = yaml.safe_load(Path(path).read_text())
    return GoldenSet(items=[GoldenItem(**row) for row in (data or {}).get("items", [])])


DEFAULT_PATH = Path(__file__).resolve().parents[3] / "eval" / "golden" / "golden_set.yaml"
