"""Domain model — the authoritative types shared across services.

Mirrors the spec's Knowledge sub-domain (docs/plans/provenance-requirements.md §2).
These are transport-neutral Pydantic models; gRPC/proto messages map onto them.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ProcessingTier(StrEnum):
    """Capability tier chosen per ingest (R13). Two tiers."""

    QUICK = "quick"  # vector only
    FULL = "full"  # vector + graph + fixed schema


class DocumentStatus(StrEnum):
    """Saga-driven document lifecycle (R5, R54)."""

    QUEUED = "queued"
    PARSING = "parsing"
    DETECTING = "detecting"
    AWAITING_CONFIRM = "awaiting_confirm"  # detect-but-confirm saga pause (R9, R55)
    EXTRACTING = "extracting"
    WRITING = "writing"
    DONE = "done"
    FAILED = "failed"


class ParseMethod(StrEnum):
    """Per-page parse method, recorded as provenance (R63)."""

    TEXT_LAYER = "text_layer"
    OCR = "ocr"


class ElementType(StrEnum):
    """Typed Parse-service element (R60)."""

    TEXT = "text"
    HEADING = "heading"
    TABLE = "table"
    FIGURE = "figure"


class BBox(BaseModel):
    """Bounding box anchoring a chunk to its source for citation highlight (R6, R36).

    Coordinates are in the page's own units (PDF points). page_width/page_height carry the
    source page's dimensions so a citation highlight normalizes correctly on any page size —
    A4, legal, etc. — instead of assuming US-Letter (review L-10). Optional for backward
    compatibility; the UI falls back to Letter when absent.
    """

    page: int = Field(ge=0)
    x0: float
    y0: float
    x1: float
    y1: float
    page_width: float | None = None
    page_height: float | None = None


class KnowledgeBase(BaseModel):
    """A named, domain-pinned collection (R1, R2)."""

    id: str
    name: str
    domain_id: str  # pinned on creation (R2)
    created_at: datetime


class Document(BaseModel):
    """A source document with provenance of how it was processed (R11, R63)."""

    id: str
    kb_id: str
    source: str
    content_type: str
    content_hash: str  # idempotency key (N5)
    tier: ProcessingTier = ProcessingTier.FULL
    status: DocumentStatus = DocumentStatus.QUEUED
    detected_domain: str | None = None
    detection_confidence: float | None = None
    schema_version: str | None = None
    schema_stale: bool = False  # set when a domain schema changes (R70)
    parse_method: ParseMethod | None = None
    ocr_engine: str | None = None
    trace_id: str | None = None  # correlates provenance to the ingestion trace (R56)
    metadata: dict[str, str] = Field(default_factory=dict)


class Chunk(BaseModel):
    """A retrievable unit carrying geometry from the Parse service (R6, R60, R68)."""

    id: str
    document_id: str
    kb_id: str
    text: str
    page: int
    bbox: BBox
    reading_order: int
    element_type: ElementType = ElementType.TEXT


class Entity(BaseModel):
    """A typed, KB-scoped graph node (R22)."""

    id: str
    kb_id: str
    type: str  # domain-specific entity type
    canonical_name: str


class Relation(BaseModel):
    """A typed edge between entities; edge properties allowed (e.g. FiscalPeriod)."""

    subject_id: str
    predicate: str
    object_id: str
    properties: dict[str, str] = Field(default_factory=dict)
