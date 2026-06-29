"""Provenance shared contracts.

Versioned, transport-neutral types shared across all services (R34, R57).
"""

from .domain import (
    BBox,
    Chunk,
    Document,
    DocumentStatus,
    ElementType,
    Entity,
    KnowledgeBase,
    ParseMethod,
    ProcessingTier,
    Relation,
)
from .extraction import EntityCandidate, ExtractionResult, RelationCandidate
from .messages import (
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
from .parse import ParsedElement, ParseResult
from .ports import QueryHit, VectorRecord, VectorStorePort
from .registry import (
    GENERIC_FALLBACK_ID,
    REGISTRY,
    DomainSpec,
    DomainTier,
)

CONTRACTS_VERSION = "v1"

__all__ = [
    "CONTRACTS_VERSION",
    # domain
    "BBox", "Chunk", "Document", "DocumentStatus", "ElementType", "Entity",
    "KnowledgeBase", "ParseMethod", "ProcessingTier", "Relation",
    # messages
    "Answer", "Citation", "Claim", "CriticStatus", "EvidenceSet", "Plan",
    "ScoredChunk", "Subquery", "SubqueryType", "Verdict",
    # extraction
    "EntityCandidate", "ExtractionResult", "RelationCandidate",
    # parse
    "ParsedElement", "ParseResult",
    # ports
    "QueryHit", "VectorRecord", "VectorStorePort",
    # registry
    "GENERIC_FALLBACK_ID", "REGISTRY", "DomainSpec", "DomainTier",
]
