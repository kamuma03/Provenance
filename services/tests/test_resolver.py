"""Entity resolver tests (R18/R19)."""

from __future__ import annotations

from provenance_contracts import EntityCandidate
from provenance_services.resolver import EntityResolver, entity_id, normalize_name


def test_normalization_collapses_surface_variants() -> None:
    assert normalize_name("The Apple Inc.") == "apple"
    assert normalize_name("APPLE  INCORPORATED") == "apple"
    assert normalize_name("Apple") == "apple"
    # All three normalize to the same id for the same type/kb.
    variants = ["The Apple Inc.", "Apple", "apple"]
    ids = {entity_id("kb1", "Company", normalize_name(n)) for n in variants}
    assert len(ids) == 1


def test_same_entity_merges_across_documents() -> None:
    r = EntityResolver()
    # Document A
    a = r.resolve("kb1", [EntityCandidate(type="Company", canonical_name="Apple Inc.")])
    assert a.created == 1 and a.merged == 0
    apple_id = a.entities[0].id
    # Document B (same entity, different surface form) — should MERGE, not duplicate (R18).
    b = r.resolve(
        "kb1",
        [EntityCandidate(type="Company", canonical_name="Apple")],
        known_ids={apple_id},
    )
    assert b.merged == 1 and b.created == 0
    assert b.name_to_id["Apple"] == apple_id  # same id => densified graph (R19)


def test_distinct_entities_get_distinct_ids() -> None:
    r = EntityResolver()
    res = r.resolve(
        "kb1",
        [
            EntityCandidate(type="Company", canonical_name="Apple"),
            EntityCandidate(type="Company", canonical_name="Microsoft"),
        ],
    )
    assert len({e.id for e in res.entities}) == 2


def test_kb_scoping_isolates_ids() -> None:
    # Same name in different KBs must not collide (R4).
    assert entity_id("kbA", "Company", "apple") != entity_id("kbB", "Company", "apple")
