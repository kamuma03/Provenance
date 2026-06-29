"""Graph service — Kuzu LPG, entity resolution, graph expansion (R22/R18/R27).

Owns entity resolution (ADR-001): /write accepts extraction candidates, resolves them to
stable ids (merging co-referents), and writes typed nodes/edges to Kuzu with provenance.
"""

from __future__ import annotations

import os

from fastapi import Request
from provenance_contracts import EntityCandidate
from provenance_service import create_app, tracer

from .graph_store import GraphStore
from .resolver import EntityResolver, normalize_name

_KUZU_PATH = os.environ.get("KUZU_DB_PATH", "/tmp/provenance-kuzu")
_store: GraphStore | None = None
_resolver = EntityResolver()


def _get_store() -> GraphStore:
    global _store
    if _store is None:
        _store = GraphStore(_KUZU_PATH)
    return _store


async def _ready() -> bool:
    try:
        _get_store()
        return True
    except Exception:
        return False


app = create_app("graph", readiness=_ready)


@app.post("/write", tags=["graph"])
async def write(req: Request) -> dict[str, object]:
    """Resolve candidates (R18) and write typed nodes/edges with provenance (R22/R56)."""
    body = await req.json()
    kb_id = body.get("kb_id", "default")
    document_id = body.get("document_id", "?")
    trace_id = body.get("trace_id")
    candidates = [EntityCandidate(**e) for e in body.get("entities", [])]
    relations = body.get("relations", [])

    with tracer("graph").start_as_current_span("graph.write") as span:
        store = _get_store()
        res = _resolver.resolve(kb_id, candidates)
        store.upsert_entities(res.entities)
        written = 0
        for r in relations:
            sid = res.name_to_id.get(r.get("subject"))
            oid = res.name_to_id.get(r.get("object"))
            if sid and oid:
                store.write_relation(
                    sid, r.get("predicate", "RELATES_TO"), oid,
                    kb_id=kb_id, document_id=document_id, trace_id=trace_id,
                )
                written += 1
        span.set_attribute("graph.entities", len(res.entities))
        span.set_attribute("graph.relations", written)
        return {
            "entities": len(res.entities),
            "relations": written,
            "merged": res.merged,
            "kb_entity_count": store.entity_count(kb_id),
        }


@app.get("/stats/{kb_id}", tags=["graph"])
async def stats(kb_id: str) -> dict[str, int]:
    return {"entity_count": _get_store().entity_count(kb_id)}


@app.post("/link", tags=["graph"])
async def link(req: Request) -> dict[str, list[str]]:
    """Query-time entity linking (R26): match query tokens to entity canonical names."""
    body = await req.json()
    kb_id = body.get("kb_id", "default")
    q_tokens = set(normalize_name(body.get("text", "")).split())
    with tracer("graph").start_as_current_span("graph.link"):
        matched: list[str] = []
        for eid, _type, name in _get_store().entities(kb_id):
            name_tokens = set(normalize_name(name).split())
            # Link when all of the entity's name tokens appear in the query.
            if name_tokens and name_tokens <= q_tokens:
                matched.append(eid)
        return {"entity_ids": matched}


@app.post("/expand", tags=["graph"])
async def expand(req: Request) -> dict[str, object]:
    body = await req.json()
    entity_id = body.get("entity_id", "")
    with tracer("graph").start_as_current_span("graph.expand"):
        neighbors = _get_store().neighbors(entity_id) if entity_id else []
        return {"entities": neighbors}  # additive graph lift (R25/R27)
