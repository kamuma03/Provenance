"""Extraction service output contract (R16).

Pre-resolution candidates: extraction proposes entities/relations by canonical name;
the entity resolver assigns ids and merges co-referents (R18), then the Graph service
writes them. Lives in contracts as the Extraction → Ingestion boundary.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EntityCandidate(BaseModel):
    type: str
    canonical_name: str


class RelationCandidate(BaseModel):
    subject: str  # canonical_name
    predicate: str
    object: str  # canonical_name
    properties: dict[str, str] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    domain_id: str
    schema_version: str
    entities: list[EntityCandidate] = Field(default_factory=list)
    relations: list[RelationCandidate] = Field(default_factory=list)
