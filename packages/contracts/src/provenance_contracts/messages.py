"""Agent message contracts — the Interaction sub-domain (spec §2, §3.I).

Typed, validated contracts between Planner / Retriever / Critic / Synthesizer (R34).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from .domain import BBox


class SubqueryType(StrEnum):
    """How the Planner types a subquery, which drives routing (R29)."""

    FACTUAL = "factual"
    RELATIONAL = "relational"
    COMPARATIVE = "comparative"


class Subquery(BaseModel):
    text: str
    type: SubqueryType


class Plan(BaseModel):
    """Planner output: decomposition + KB scope + a declared synthesis strategy (R29)."""

    kb_scope: list[str]
    subqueries: list[Subquery]
    synthesis_strategy: str  # e.g. "set_difference" for comparative (R33)


class ScoredChunk(BaseModel):
    chunk_id: str
    text: str
    page: int
    bbox: BBox
    score: float


class SubgraphNode(BaseModel):
    """A named, typed entity used in an answer (R37)."""

    id: str
    name: str
    type: str


class SubgraphEdge(BaseModel):
    """A typed relation between two entities used in an answer (R37)."""

    src: str
    dst: str
    type: str


class Subgraph(BaseModel):
    """The per-answer entity subgraph the UI renders (R37) — nodes + edges, not raw ids."""

    nodes: list[SubgraphNode] = Field(default_factory=list)
    edges: list[SubgraphEdge] = Field(default_factory=list)


class EvidenceSet(BaseModel):
    """Retriever output for one subquery (R30)."""

    subquery: str
    chunks: list[ScoredChunk] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    graph_expanded: bool = False  # whether additive graph lift contributed (R25)
    subgraph: Subgraph = Field(default_factory=Subgraph)  # named/typed nodes+edges (R37)


class Citation(BaseModel):
    chunk_id: str
    page: int
    bbox: BBox


class Claim(BaseModel):
    """An atomic, verifiable assertion (R65). Strict refusal operates at this granularity."""

    text: str
    citations: list[Citation] = Field(default_factory=list)
    grounded: bool | None = None  # set by the Critic


class Answer(BaseModel):
    """Synthesizer output: text decomposed into cited claims (R33, R65)."""

    text: str
    claims: list[Claim] = Field(default_factory=list)
    refused: bool = False  # honest refusal (R39) or strict-refusal exhaustion (R32)
    refusal_reason: str | None = None
    ungrounded_claims: list[str] = Field(default_factory=list)  # Critic verdict, surfaced (R31)


class CriticStatus(StrEnum):
    OK = "ok"
    REVISE = "revise"


class Verdict(BaseModel):
    """Critic verdict gating release; strict whole-answer groundedness (R31, R32)."""

    status: CriticStatus
    ungrounded_claims: list[str] = Field(default_factory=list)
