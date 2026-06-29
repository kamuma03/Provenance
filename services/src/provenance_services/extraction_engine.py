"""Schema-driven extraction (R16/R17).

Extraction conforms to the selected domain's typed schema: candidates whose type/predicate
are not in the domain's registry entry are repaired-by-dropping, never persisted raw. A
real heuristic extractor runs for the generic domain without an LLM; typed-domain
extraction uses an injectable LLM extractor (the Spark path), validated the same way.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

from provenance_contracts import (
    GENERIC_FALLBACK_ID,
    DomainSpec,
    EntityCandidate,
    ExtractionResult,
    RelationCandidate,
)
from provenance_service import LLMClient

SCHEMA_VERSION = "v1"

# Async; returns raw {"entities": [{"type","canonical_name"}], "relations": [...]}.
LLMExtractor = Callable[[str, DomainSpec], Awaitable[dict]]

_PROPER = re.compile(r"\b([A-Z][a-zA-Z0-9.&]+(?:\s+[A-Z][a-zA-Z0-9.&]+)*)\b")
_ORG_SUFFIX = ("Inc", "Inc.", "Corp", "Corp.", "Ltd", "LLC", "PLC", "Co", "Co.")


def heuristic_generic(text: str) -> list[EntityCandidate]:
    """No-LLM extraction for the generic domain: proper-noun phrases as entities."""
    seen: dict[str, EntityCandidate] = {}
    for m in _PROPER.finditer(text):
        phrase = m.group(1).strip()
        if len(phrase) < 3 or phrase.lower() in seen:
            continue
        etype = "Organization" if phrase.split()[-1] in _ORG_SUFFIX else "Concept"
        seen[phrase.lower()] = EntityCandidate(type=etype, canonical_name=phrase)
    return list(seen.values())


def validate_against_schema(
    entities: list[EntityCandidate],
    relations: list[RelationCandidate],
    spec: DomainSpec,
) -> tuple[list[EntityCandidate], list[RelationCandidate]]:
    """Repair-by-dropping anything off-schema (R16)."""
    allowed_types = set(spec.entity_types)
    kept = [e for e in entities if e.type in allowed_types]
    names = {e.canonical_name for e in kept}
    allowed_preds = set(spec.relation_types)
    kept_rels = [
        r
        for r in relations
        if r.predicate in allowed_preds and r.subject in names and r.object in names
    ]
    return kept, kept_rels


async def extract(
    text: str, spec: DomainSpec, llm: LLMExtractor | None = None
) -> ExtractionResult:
    """Extract typed entities/relations, validated against the domain schema."""
    if llm is not None:
        raw = await llm(text, spec)
        entities = [EntityCandidate(**e) for e in raw.get("entities", [])]
        relations = [RelationCandidate(**r) for r in raw.get("relations", [])]
    elif spec.id == GENERIC_FALLBACK_ID:
        entities, relations = heuristic_generic(text), []
    else:
        # Typed-domain extraction without an LLM yields nothing (real path = LLM on Spark).
        entities, relations = [], []

    entities, relations = validate_against_schema(entities, relations, spec)
    return ExtractionResult(
        domain_id=spec.id,
        schema_version=SCHEMA_VERSION,
        entities=entities,
        relations=relations,
    )


def make_llm_extractor(client: LLMClient) -> LLMExtractor:
    """Bridge an LLMClient to the LLMExtractor interface (typed-domain extraction, R16)."""

    async def _extract(text: str, spec: DomainSpec) -> dict:
        system = (
            f"Extract entities and relations for the '{spec.name}' domain. "
            f"Allowed entity types: {spec.entity_types}. "
            f"Allowed relation predicates: {spec.relation_types}. "
            'Reply with JSON only: {"entities": [{"type": "...", "canonical_name": "..."}], '
            '"relations": [{"subject": "...", "predicate": "...", "object": "..."}]}.'
        )
        raw = await client.complete(system, text)
        try:
            return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        except Exception:
            return {"entities": [], "relations": []}

    return _extract
