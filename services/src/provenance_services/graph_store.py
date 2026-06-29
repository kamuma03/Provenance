"""Kuzu graph store (R22) — typed nodes/edges, kb_id-partitioned, with provenance.

Writes are MERGE-based and keyed on the resolver's stable entity ids, so re-ingesting a
co-referent entity densifies the graph instead of duplicating (R18/R19). Relations carry
kb_id + document_id + trace_id for provenance (R56). Embedded (no server) per ADR-001.
"""

from __future__ import annotations

import kuzu
from provenance_contracts import Entity
from pydantic import BaseModel


class WriteResult(BaseModel):
    entities_written: int
    relations_written: int


class GraphStore:
    def __init__(self, db_path: str) -> None:
        self._db = kuzu.Database(db_path)
        self._conn = kuzu.Connection(self._db)
        self._init_schema()

    def _init_schema(self) -> None:
        for ddl in (
            "CREATE NODE TABLE IF NOT EXISTS Entity("
            "id STRING PRIMARY KEY, kb_id STRING, type STRING, canonical_name STRING)",
            "CREATE REL TABLE IF NOT EXISTS Rel(FROM Entity TO Entity, "
            "predicate STRING, kb_id STRING, document_id STRING, trace_id STRING)",
        ):
            self._conn.execute(ddl)

    def upsert_entities(self, entities: list[Entity]) -> int:
        for e in entities:
            self._conn.execute(
                "MERGE (n:Entity {id: $id}) "
                "SET n.kb_id = $kb, n.type = $type, n.canonical_name = $name",
                {"id": e.id, "kb": e.kb_id, "type": e.type, "name": e.canonical_name},
            )
        return len(entities)

    def write_relation(
        self,
        subject_id: str,
        predicate: str,
        object_id: str,
        *,
        kb_id: str,
        document_id: str,
        trace_id: str | None = None,
    ) -> None:
        self._conn.execute(
            "MATCH (a:Entity {id: $s}), (b:Entity {id: $o}) "
            "MERGE (a)-[r:Rel {predicate: $p}]->(b) "
            "SET r.kb_id = $kb, r.document_id = $doc, r.trace_id = $tid",
            {"s": subject_id, "o": object_id, "p": predicate,
             "kb": kb_id, "doc": document_id, "tid": trace_id or ""},
        )

    def entity_count(self, kb_id: str) -> int:
        res = self._conn.execute(
            "MATCH (e:Entity) WHERE e.kb_id = $kb RETURN count(e)", {"kb": kb_id}
        )
        return int(res.get_next()[0]) if res.has_next() else 0

    def neighbors(self, entity_id: str) -> list[str]:
        """1-hop neighbor ids — the basis for additive graph expansion (R27)."""
        res = self._conn.execute(
            "MATCH (a:Entity {id: $id})-[:Rel]-(b:Entity) RETURN DISTINCT b.id", {"id": entity_id}
        )
        out: list[str] = []
        while res.has_next():
            out.append(res.get_next()[0])
        return out

    def close(self) -> None:
        self._conn.close()
        self._db.close()
