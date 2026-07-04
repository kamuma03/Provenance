"""Graph service — Kuzu LPG, entity resolution, graph expansion (R22/R18/R27).

Owns entity resolution (ADR-001): /write accepts extraction candidates, resolves them to
stable ids (merging co-referents), and writes typed nodes/edges to Kuzu with provenance.
"""

from __future__ import annotations

import logging
import os
import threading

import anyio
from provenance_contracts import EntityCandidate
from provenance_service import create_app, tracer
from pydantic import BaseModel, Field

from .graph_store import GraphStore
from .resolver import EntityResolver, normalize_name

log = logging.getLogger("graph")


# Typed internal request bodies (N9, review M-5).
class WriteRequest(BaseModel):
    kb_id: str = "default"
    document_id: str = "?"
    trace_id: str | None = None
    entities: list[EntityCandidate] = Field(default_factory=list)
    relations: list[dict[str, object]] = Field(default_factory=list)


class DeleteRequest(BaseModel):
    document_id: str = ""


class LinkRequest(BaseModel):
    kb_id: str = "default"
    text: str = ""


class ExpandRequest(BaseModel):
    entity_id: str = ""

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
        # Pass the KB's existing entity ids so merged-vs-created is counted correctly, instead
        # of reporting every entity as newly created (review L-1).
        known = {eid for eid, _t, _n in store.entities(kb_id)}
        res = _resolver.resolve(kb_id, candidates, known_ids=known)
        store.upsert_entities(res.entities)

        def _endpoint(name: object) -> str | None:
            # Resolve a relation endpoint by exact name, then by normalized form, so a drifted
            # surface form doesn't silently drop the edge (review M-7).
            if not isinstance(name, str):
                return None
            return res.name_to_id.get(name) or res.name_to_id.get(normalize_name(name))

        written = 0
        dropped = 0
        for r in relations:
            sid, oid = _endpoint(r.get("subject")), _endpoint(r.get("object"))
            if sid and oid:
                store.write_relation(
                    sid, str(r.get("predicate", "RELATES_TO")), oid,
                    kb_id=kb_id, document_id=document_id, trace_id=trace_id,
                )
                written += 1
            else:
                dropped += 1
        if dropped:
            log.warning(
                "graph.write dropped %d relation(s) with unresolved endpoints (doc=%s)",
                dropped, document_id,
            )
        return {
            "entities": len(res.entities),
            "relations": written,
            "relations_dropped": dropped,
            "merged": res.merged,
            "kb_entity_count": store.entity_count(kb_id),
        }


@app.post("/write", tags=["graph"])
async def write(body: WriteRequest) -> dict[str, object]:
    """Resolve candidates (R18) and write typed nodes/edges with provenance (R22/R56)."""
    with tracer("graph").start_as_current_span("graph.write") as span:
        result = await anyio.to_thread.run_sync(
            _write_sync, body.kb_id, body.document_id, body.trace_id,
            body.entities, body.relations,
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
async def link(body: LinkRequest) -> dict[str, list[str]]:
    """Query-time entity linking (R26): match query tokens to entity canonical names."""
    with tracer("graph").start_as_current_span("graph.link"):
        matched = await anyio.to_thread.run_sync(_link_sync, body.kb_id, body.text)
        return {"entity_ids": matched}


def _delete_sync(document_id: str) -> int:
    store = _get_store()
    with _access_lock:
        return store.delete_document(document_id)


@app.post("/delete", tags=["graph"])
async def delete(body: DeleteRequest) -> dict[str, int]:
    """Delete a document's relations (saga compensation, R54/H-3)."""
    with tracer("graph").start_as_current_span("graph.delete") as span:
        removed = (
            await anyio.to_thread.run_sync(_delete_sync, body.document_id)
            if body.document_id else 0
        )
        span.set_attribute("graph.deleted", removed)
        return {"deleted": removed}


def _expand_sync(entity_id: str) -> list[str]:
    if not entity_id:
        return []
    store = _get_store()
    with _access_lock:
        return store.neighbors(entity_id)


@app.post("/expand", tags=["graph"])
async def expand(body: ExpandRequest) -> dict[str, object]:
    with tracer("graph").start_as_current_span("graph.expand"):
        neighbors = await anyio.to_thread.run_sync(_expand_sync, body.entity_id)
        return {"entities": neighbors}  # additive graph lift (R25/R27)
