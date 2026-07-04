"""Kuzu graph store (R22) — typed nodes/edges, kb_id-partitioned, with provenance.

Writes are MERGE-based and keyed on the resolver's stable entity ids, so re-ingesting a
co-referent entity densifies the graph instead of duplicating (R18/R19). Relations carry
kb_id + document_id + trace_id for provenance (R56). Embedded (no server) per ADR-001.
"""

from __future__ import annotations

from typing import Any, cast

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
        # Include document_id in the MERGE key so a second document asserting the same
        # relation adds its own edge rather than overwriting the first document's provenance
        # (last-writer-wins would make r.document_id lie about origin — review M-6). Re-asserting
        # from the *same* document stays idempotent.
        self._conn.execute(
            "MATCH (a:Entity {id: $s}), (b:Entity {id: $o}) "
            "MERGE (a)-[r:Rel {predicate: $p, document_id: $doc}]->(b) "
            "SET r.kb_id = $kb, r.trace_id = $tid",
            {"s": subject_id, "o": object_id, "p": predicate,
             "kb": kb_id, "doc": document_id, "tid": trace_id or ""},
        )

    def _query(self, statement: str, params: dict[str, Any]) -> kuzu.QueryResult:
        """Execute a single read statement (always one QueryResult, never a list)."""
        return cast("kuzu.QueryResult", self._conn.execute(statement, params))

    def entity_count(self, kb_id: str) -> int:
        res = self._query(
            "MATCH (e:Entity) WHERE e.kb_id = $kb RETURN count(e)", {"kb": kb_id}
        )
        return int(cast("list[Any]", res.get_next())[0]) if res.has_next() else 0

    def entities(self, kb_id: str) -> list[tuple[str, str, str]]:
        """All (id, type, canonical_name) for a KB — basis for query-time linking (R26)."""
        res = self._query(
            "MATCH (e:Entity) WHERE e.kb_id = $kb RETURN e.id, e.type, e.canonical_name",
            {"kb": kb_id},
        )
        out: list[tuple[str, str, str]] = []
        while res.has_next():
            row = cast("list[Any]", res.get_next())
            out.append((row[0], row[1], row[2]))
        return out

    def neighbors(self, entity_id: str) -> list[str]:
        """1-hop neighbor ids — the basis for additive graph expansion (R27)."""
        res = self._query(
            "MATCH (a:Entity {id: $id})-[:Rel]-(b:Entity) RETURN DISTINCT b.id", {"id": entity_id}
        )
        out: list[str] = []
        while res.has_next():
            out.append(cast("list[Any]", res.get_next())[0])
        return out

    def delete_document(self, document_id: str) -> int:
        """Delete the relations this document authored (saga compensation, R54/review H-3).

        Only relations carry document_id; entities are resolved/merged and may be shared
        across documents, so they are intentionally left intact — removing them could erase
        another document's provenance."""
        res = self._query(
            "MATCH ()-[r:Rel]->() WHERE r.document_id = $doc RETURN count(r)",
            {"doc": document_id},
        )
        count = int(cast("list[Any]", res.get_next())[0]) if res.has_next() else 0
        if count:
            self._conn.execute(
                "MATCH ()-[r:Rel]->() WHERE r.document_id = $doc DELETE r", {"doc": document_id}
            )
        return count

    def close(self) -> None:
        self._conn.close()
        self._db.close()
