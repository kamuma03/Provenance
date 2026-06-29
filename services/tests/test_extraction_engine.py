"""Schema-driven extraction tests (R16/R17)."""

from __future__ import annotations

import pytest
from provenance_contracts import REGISTRY, DomainSpec, DomainTier
from provenance_services.extraction_engine import (
    extract,
    heuristic_generic,
    validate_against_schema,
)


def test_heuristic_generic_extracts_proper_nouns() -> None:
    text = "Apple Inc. reported strong results. The Federal Reserve raised rates."
    ents = heuristic_generic(text)
    names = {e.canonical_name for e in ents}
    assert "Apple Inc" in names  # trailing period dropped at the word boundary
    assert any(e.type == "Organization" for e in ents)  # Inc suffix => Organization


@pytest.mark.asyncio
async def test_generic_domain_extraction_runs_without_llm() -> None:
    spec = REGISTRY["generic"]
    result = await extract("Tesla Inc. and the World Bank met in Geneva.", spec)
    assert result.domain_id == "generic"
    assert result.schema_version == "v1"
    assert result.entities  # heuristic produced something


def test_validation_drops_off_schema_types_and_relations() -> None:
    from provenance_contracts import EntityCandidate, RelationCandidate

    spec = REGISTRY["sec_financial"]  # types include Company, Auditor; rels include AUDITED_BY
    entities = [
        EntityCandidate(type="Company", canonical_name="Apple"),
        EntityCandidate(type="Auditor", canonical_name="EY"),
        EntityCandidate(type="Wizard", canonical_name="Gandalf"),  # off-schema → dropped
    ]
    relations = [
        RelationCandidate(subject="Apple", predicate="AUDITED_BY", object="EY"),  # valid
        RelationCandidate(subject="Apple", predicate="CASTS_SPELL", object="EY"),  # bad predicate
        RelationCandidate(subject="Apple", predicate="AUDITED_BY", object="Gandalf"),  # dropped ent
    ]
    kept_e, kept_r = validate_against_schema(entities, relations, spec)
    assert {e.canonical_name for e in kept_e} == {"Apple", "EY"}
    assert len(kept_r) == 1 and kept_r[0].predicate == "AUDITED_BY"


@pytest.mark.asyncio
async def test_typed_domain_uses_injected_llm_and_validates() -> None:
    spec = REGISTRY["sec_financial"]

    async def fake_llm(text: str, spec: DomainSpec) -> dict:
        return {
            "entities": [
                {"type": "Company", "canonical_name": "Apple Inc."},
                {"type": "Nonsense", "canonical_name": "Bad"},  # off-schema
            ],
            "relations": [],
        }

    result = await extract("...", spec, llm=fake_llm)
    assert [e.canonical_name for e in result.entities] == ["Apple Inc."]  # off-schema dropped


@pytest.mark.asyncio
async def test_make_llm_extractor_parses_json_and_drops_off_schema() -> None:
    from provenance_service import MockLLMClient
    from provenance_services.extraction_engine import make_llm_extractor

    spec = REGISTRY["sec_financial"]
    raw = '{"entities": [{"type": "Company", "canonical_name": "Apple Inc."}], "relations": []}'
    extractor = make_llm_extractor(MockLLMClient([raw]))
    result = await extract("Apple Inc. filed a 10-K.", spec, llm=extractor)
    assert [e.canonical_name for e in result.entities] == ["Apple Inc."]


def test_registry_tiers_intact() -> None:
    # Sanity: extraction respects the registry shape it depends on.
    assert REGISTRY["sec_financial"].tier is DomainTier.BUILT
