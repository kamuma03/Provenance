"""Kuzu graph store tests (R22/R18/R4) — runs against a real embedded Kuzu DB."""

from __future__ import annotations

from pathlib import Path

from provenance_contracts import Entity
from provenance_services.graph_store import GraphStore


def _ent(eid: str, kb: str, etype: str, name: str) -> Entity:
    return Entity(id=eid, kb_id=kb, type=etype, canonical_name=name)


def test_write_entities_relations_and_neighbors(tmp_path: Path) -> None:
    gs = GraphStore(str(tmp_path / "g1"))
    try:
        gs.upsert_entities([
            _ent("e_apple", "kb1", "Company", "Apple"),
            _ent("e_ey", "kb1", "Auditor", "EY"),
        ])
        gs.write_relation(
            "e_apple", "AUDITED_BY", "e_ey", kb_id="kb1", document_id="d1", trace_id="t1"
        )

        assert gs.entity_count("kb1") == 2
        assert gs.neighbors("e_apple") == ["e_ey"]  # 1-hop expansion basis (R27)
    finally:
        gs.close()


def test_merge_is_idempotent(tmp_path: Path) -> None:
    gs = GraphStore(str(tmp_path / "g2"))
    try:
        e = _ent("e_apple", "kb1", "Company", "Apple")
        gs.upsert_entities([e])
        gs.upsert_entities([e])  # same id again — must not duplicate (R18)
        assert gs.entity_count("kb1") == 1
    finally:
        gs.close()


def test_delete_document_removes_its_relations_but_keeps_shared_entities(tmp_path: Path) -> None:
    # Saga compensation for a failed graph write: drop the document's relations, leave the
    # resolved (possibly shared) entities intact (R54, review H-3).
    gs = GraphStore(str(tmp_path / "g4"))
    try:
        gs.upsert_entities([
            _ent("e_apple", "kb1", "Company", "Apple"),
            _ent("e_ey", "kb1", "Auditor", "EY"),
        ])
        gs.write_relation("e_apple", "AUDITED_BY", "e_ey", kb_id="kb1", document_id="d1")
        gs.write_relation("e_apple", "MENTIONS", "e_ey", kb_id="kb1", document_id="d2")

        removed = gs.delete_document("d1")
        assert removed == 1
        assert gs.neighbors("e_apple") == ["e_ey"]  # d2's relation still links them
        assert gs.entity_count("kb1") == 2  # entities are not deleted
        assert gs.delete_document("d1") == 0  # idempotent
    finally:
        gs.close()


def test_kb_partitioning_isolates_subgraphs(tmp_path: Path) -> None:
    gs = GraphStore(str(tmp_path / "g3"))
    try:
        gs.upsert_entities([_ent("e_a", "kbA", "Company", "Apple")])
        gs.upsert_entities([_ent("e_b", "kbB", "Company", "Acme")])
        assert gs.entity_count("kbA") == 1
        assert gs.entity_count("kbB") == 1  # each KB sees only its own (R4)
    finally:
        gs.close()
