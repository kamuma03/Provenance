"""P0 gate: contracts validate (no feature logic).

Proves the shared domain/message/port/registry contracts instantiate and hold their
invariants — the foundation every service depends on.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from provenance_contracts import (
    CONTRACTS_VERSION,
    REGISTRY,
    Answer,
    BBox,
    Chunk,
    Claim,
    CriticStatus,
    Document,
    DocumentStatus,
    DomainTier,
    Entity,
    EvidenceSet,
    KnowledgeBase,
    Plan,
    ProcessingTier,
    QueryHit,
    Subquery,
    SubqueryType,
    VectorRecord,
    VectorStorePort,
    Verdict,
)
from pydantic import ValidationError


def test_contracts_version() -> None:
    assert CONTRACTS_VERSION == "v1"


def test_domain_models_instantiate() -> None:
    kb = KnowledgeBase(
        id="kb1", name="SEC", domain_id="sec_financial", created_at=datetime(2026, 1, 1)
    )
    doc = Document(
        id="d1", kb_id=kb.id, source="apple-10k.pdf", content_type="application/pdf",
        content_hash="abc123", tier=ProcessingTier.FULL, status=DocumentStatus.QUEUED,
    )
    chunk = Chunk(
        id="c1", document_id=doc.id, kb_id=kb.id, text="hello",
        page=1, bbox=BBox(page=1, x0=0, y0=0, x1=1, y1=1), reading_order=0,
    )
    ent = Entity(id="e1", kb_id=kb.id, type="Company", canonical_name="Apple Inc.")
    assert chunk.bbox.page == 1
    assert ent.type == "Company"
    assert doc.status is DocumentStatus.QUEUED


def test_message_contracts_instantiate() -> None:
    plan = Plan(
        kb_scope=["kb1"],
        subqueries=[Subquery(text="risk factors in 2022", type=SubqueryType.COMPARATIVE)],
        synthesis_strategy="set_difference",
    )
    assert plan.subqueries[0].type is SubqueryType.COMPARATIVE
    es = EvidenceSet(subquery="x")
    assert es.graph_expanded is False
    ans = Answer(text="...", claims=[Claim(text="Apple cited risk X")])
    assert ans.refused is False
    v = Verdict(status=CriticStatus.REVISE, ungrounded_claims=["Apple cited risk X"])
    assert v.status is CriticStatus.REVISE


def test_registry_shape() -> None:
    # Generic fallback exists and is Built.
    assert "generic" in REGISTRY
    assert REGISTRY["generic"].tier is DomainTier.BUILT

    built = [d for d in REGISTRY.values() if d.tier is DomainTier.BUILT]
    built_ids = {d.id for d in built}
    # Four real Built domains + generic (spec §1, Appendix A).
    assert built_ids == {
        "sec_financial", "research_papers", "legal_contracts",
        "technical_software", "generic",
    }

    # Registry-ready domains are detector-routable schema entries (R48).
    ready = {d.id for d in REGISTRY.values() if d.tier is DomainTier.REGISTRY_READY}
    assert ready == {"biomedical_clinical", "regulatory_standards", "patents"}

    # Every non-generic domain has typed entities and relations.
    for spec in REGISTRY.values():
        assert spec.entity_types, f"{spec.id} missing entity types"
        assert spec.relation_types, f"{spec.id} missing relation types"


def test_vector_store_port_is_structural() -> None:
    """A conforming stub satisfies the Port (R20); a non-conforming one does not."""

    class StubVectorStore:
        async def upsert(self, namespace: str, records: list[VectorRecord]) -> None: ...

        async def query(self, namespace, vector, k, filter=None) -> list[QueryHit]:
            return []

        async def hybrid_query(self, namespace, vector, text, k, filter=None) -> list[QueryHit]:
            return []

        async def delete(self, namespace: str, document_id: str) -> int:
            return 0

    assert isinstance(StubVectorStore(), VectorStorePort)
    assert not isinstance(object(), VectorStorePort)


def test_pydantic_validation_rejects_bad_data() -> None:
    with pytest.raises(ValidationError):
        BBox(page=-1, x0=0, y0=0, x1=1, y1=1)  # page must be >= 0
