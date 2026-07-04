"""Graph service — Kuzu LPG, entity resolution, graph expansion (R22/R18/R27).

Owns entity resolution (ADR-001): /write accepts extraction candidates, resolves them to
stable ids (merging co-referents), and writes typed nodes/edges to Kuzu with provenance.
"""

from __future__ import annotations

import os
import threading

import anyio
from fastapi import Request
from provenance_contracts import EntityCandidate
from provenance_service import create_app, tracer

from .graph_store import GraphStore
from .resolver import EntityResolver, normalize_name

_KUZU_PATH = os.environ.get("KUZU_DB_PATH", "/tmp/provenance-kuzu")
_store: GraphStore | None = None
_resolver = EntityResolver()

# Kuzu queries run on a thread pool (H-5) so they don't block the event loop / health probes.
# _init_lock guards one-time store construction (fast — readiness may touch it); _access_lock
# serializes the non-thread-safe Kuzu connection + shared resolver during actual queries.
_init_lock = threading.Lock()
_access_lock = threading.RLock()


def _get_store() -> GraphStore:
    global _store
    with _init_lock:
        if _store is None:
            _store = GraphStore(_KUZU_PATH)
        return _store


async def _ready() -> bool:
    try:
        _get_store()  # only constructs; does not take _access_lock, so a long query can't block it
        return True
    except Exception:
        return False


app = create_app("graph", readiness=_ready)


def _write_sync(
    kb_id: str, document_id: str, trace_id: str | None,
    candidates: list[EntityCandidate], relations: list[dict[str, object]],
) -> dict[str, int]:
    store = _get_store()
    with _access_lock:
        res = _resolver.resolve(kb_id, candidates)
        store.upsert_entities(res.entities)
        written = 0
        for r in relations:
            subject, obj = r.get("subject"), r.get("object")
            sid = res.name_to_id.get(subject) if isinstance(subject, str) else None
            oid = res.name_to_id.get(obj) if isinstance(obj, str) else None
            if sid and oid:
                store.write_relation(
                    sid, str(r.get("predicate", "RELATES_TO")), oid,
                    kb_id=kb_id, document_id=document_id, trace_id=trace_id,
                )
                written += 1
        return {
            "entities": len(res.entities),
            "relations": written,
            "merged": res.merged,
            "kb_entity_count": store.entity_count(kb_id),
        }


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
        result = await anyio.to_thread.run_sync(
            _write_sync, kb_id, document_id, trace_id, candidates, relations
        )
        span.set_attribute("graph.entities", result["entities"])
        span.set_attribute("graph.relations", result["relations"])
        return dict(result)


def _stats_sync(kb_id: str) -> int:
    store = _get_store()
    with _access_lock:
        return store.entity_count(kb_id)


@app.get("/stats/{kb_id}", tags=["graph"])
async def stats(kb_id: str) -> dict[str, int]:
    count = await anyio.to_thread.run_sync(_stats_sync, kb_id)
    return {"entity_count": count}


def _link_sync(kb_id: str, text: str) -> list[str]:
    # NOTE: this scans every entity in the KB (O(corpus)); a Kuzu-side token index is a
    # worthwhile follow-up, but for now it at least runs off the event loop (H-5).
    q_tokens = set(normalize_name(text).split())
    store = _get_store()
    with _access_lock:
        entities = store.entities(kb_id)
    matched: list[str] = []
    for eid, _type, name in entities:
        name_tokens = set(normalize_name(name).split())
        if name_tokens and name_tokens <= q_tokens:  # all name tokens present in the query
            matched.append(eid)
    return matched


@app.post("/link", tags=["graph"])
async def link(req: Request) -> dict[str, list[str]]:
    """Query-time entity linking (R26): match query tokens to entity canonical names."""
    body = await req.json()
    kb_id = body.get("kb_id", "default")
    text = body.get("text", "")
    with tracer("graph").start_as_current_span("graph.link"):
        matched = await anyio.to_thread.run_sync(_link_sync, kb_id, text)
        return {"entity_ids": matched}


def _delete_sync(document_id: str) -> int:
    store = _get_store()
    with _access_lock:
        return store.delete_document(document_id)


@app.post("/delete", tags=["graph"])
async def delete(req: Request) -> dict[str, int]:
    """Delete a document's relations (saga compensation, R54/H-3)."""
    body = await req.json()
    document_id = body.get("document_id", "")
    with tracer("graph").start_as_current_span("graph.delete") as span:
        removed = await anyio.to_thread.run_sync(_delete_sync, document_id) if document_id else 0
        span.set_attribute("graph.deleted", removed)
        return {"deleted": removed}


def _expand_sync(entity_id: str) -> list[str]:
    if not entity_id:
        return []
    store = _get_store()
    with _access_lock:
        return store.neighbors(entity_id)


@app.post("/expand", tags=["graph"])
async def expand(req: Request) -> dict[str, object]:
    body = await req.json()
    entity_id = body.get("entity_id", "")
    with tracer("graph").start_as_current_span("graph.expand"):
        neighbors = await anyio.to_thread.run_sync(_expand_sync, entity_id)
        return {"entities": neighbors}  # additive graph lift (R25/R27)
