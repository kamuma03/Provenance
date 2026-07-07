"""Gateway / BFF — the REST/SSE edge + ingestion-saga entry point (R51, R53, R54).

Owns the Catalog. Accepts uploads (base64 content), enqueues an ingest job on NATS, and
proxies queries to Query/Agent. Subscribes to saga status events and writes Document
status transitions to the catalog (B.4). Returns 202 quickly on the async ingest path.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from provenance_service import NatsBus, ServiceSettings, create_app, tracer
from pydantic import BaseModel

from .catalog import Catalog
from .clients import call, call_get

log = logging.getLogger("gateway")


# Typed request bodies for the public edge (N9): validated by FastAPI and surfaced in the
# OpenAPI schema, so a missing `query` is a 422 instead of a silent empty-string default
# (review M-5). Internal service-to-service endpoints stay dict-based for now — see the plan.
class QueryRequest(BaseModel):
    query: str
    # Multi-KB scope (R38/R-BE-2). `kb_id` stays for a dual-running release and is normalized
    # into `kb_ids=[kb_id]`; `kb_ids=[x]` retrieves byte-identically to the legacy `kb_id=x`.
    kb_id: str | None = None
    kb_ids: list[str] | None = None

    def scope(self) -> list[str]:
        if self.kb_ids:
            return list(self.kb_ids)
        return [self.kb_id] if self.kb_id else ["default"]


class KbRequest(BaseModel):
    name: str = "untitled"
    domain_id: str = "generic"


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

settings = ServiceSettings(service_name="gateway")
bus = NatsBus(settings.nats_url)
catalog = Catalog()

INGEST_SUBJECT = "ingest.jobs"
STATUS_SUBJECT = "ingest.status"
CONFIRM_SUBJECT = "ingest.confirm"
INGEST_STREAM = "INGEST"


# In-process SSE fan-out (R-BE-7): the gateway already holds ONE durable subscription to the
# status subject (`_on_status`). Rather than open a NATS subscription per browser, live
# document feeds register an asyncio.Queue here and `_on_status` pushes each event to the
# listeners for that document. Keyed by document_id; a set supports several viewers at once.
_sse_listeners: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}


def _register_listener(doc_id: str) -> asyncio.Queue[dict[str, Any]]:
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _sse_listeners.setdefault(doc_id, set()).add(q)
    return q


def _unregister_listener(doc_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
    listeners = _sse_listeners.get(doc_id)
    if listeners is not None:
        listeners.discard(q)
        if not listeners:
            _sse_listeners.pop(doc_id, None)


def _fan_out(doc_id: str, evt: dict[str, Any]) -> None:
    for q in list(_sse_listeners.get(doc_id, ())):
        q.put_nowait(evt)


async def _on_status(data: bytes, _headers: dict[str, str]) -> None:
    evt = json.loads(data or b"{}")
    doc_id = evt.get("document_id")
    if not doc_id:
        return
    # Forward every event to any live document feed first, so the SSE stepper sees both the
    # per-stage progress and the coarse lifecycle transitions (R-BE-7).
    _fan_out(doc_id, evt)
    # Per-stage saga progress (R-BE-6): record which stage is active and leave the coarse
    # `document.status` lifecycle string untouched — the two are separate signals.
    stage, state = evt.get("stage"), evt.get("state")
    if stage and state:
        await catalog.record_progress(doc_id, stage, state)
        return
    status = evt.get("status")
    if not status:
        return
    provenance = evt.get("provenance")
    if provenance:  # terminal 'done' carries how the document was processed (R56, H-9)
        await catalog.record_provenance(doc_id, status, provenance)
    else:
        await catalog.update_status(doc_id, status)


async def _on_startup() -> None:
    await bus.connect()
    await catalog.connect()
    # Durable stream for ingest jobs so a queued document survives an ingestion restart (H-3).
    await bus.ensure_stream(INGEST_STREAM, [INGEST_SUBJECT])
    await bus.subscribe(STATUS_SUBJECT, _on_status, queue="gateway")


async def _on_shutdown() -> None:
    await bus.close()
    await catalog.close()


async def _ready() -> bool:
    return bus.connected


app = create_app(
    "gateway", settings=settings, readiness=_ready,
    on_startup=_on_startup, on_shutdown=_on_shutdown,
)

# The Gateway is the browser-facing edge (R51); the Next.js UI fetches it cross-origin, so
# it needs CORS (the internal services don't). Origins are configurable; default to the
# local dev UI. No credentials are used, so "*" is a valid wildcard if set.
import os  # noqa: E402

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

_cors_origins = [
    o.strip() for o in os.environ.get("CORS_ALLOW_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/kb", tags=["gateway"])
async def create_kb(body: KbRequest) -> dict[str, str]:
    kb_id = f"kb_{uuid.uuid4().hex[:8]}"
    await catalog.create_kb(kb_id, body.name, body.domain_id)
    return {"id": kb_id}


@app.get("/kb", tags=["gateway"])
async def list_kb() -> list[dict[str, object]]:
    """List KBs for the chat/ingest selector (R-BE-1 / R-UI-1)."""
    return await catalog.list_kb()


@app.get("/chunks/{chunk_id}", tags=["gateway"])
async def get_chunk(chunk_id: str) -> JSONResponse:
    """Fetch one chunk (text + page + bbox) for the source inspector (R-BE-5 / R-UI-3)."""
    chunk = await catalog.get_chunk(chunk_id)
    return JSONResponse(status_code=200 if chunk else 404, content=chunk or {"error": "not found"})


@app.post("/kb/{kb_id}/documents", tags=["gateway"])
async def upload_document(kb_id: str, req: Request) -> JSONResponse:
    """Upload (R5): persist queued Document, enqueue saga job with content, return 202."""
    body = await req.json()
    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    source = body.get("source", "unknown")
    # Accept base64 PDF (content_b64) or plain text (content).
    content_b64 = body.get("content_b64")
    if content_b64 is None:
        content_b64 = base64.b64encode((body.get("content") or source).encode()).decode()
    try:
        raw = base64.b64decode(content_b64, validate=True)
    except (binascii.Error, ValueError):
        return JSONResponse(status_code=400, content={"error": "content_b64 is not valid base64"})
    content_hash = hashlib.sha256(raw).hexdigest()  # idempotency key (N5)
    with tracer("gateway").start_as_current_span("gateway.upload"):
        result = await catalog.create_document(
            doc_id, kb_id, source, "application/octet-stream", content_hash
        )
        if result is not None:
            doc_id, created = result
            if not created:
                # Idempotent re-upload (e.g. a retry after a 202 timeout): return the existing
                # document and do NOT re-run the saga, which would duplicate chunks (H-4).
                return JSONResponse(
                    status_code=200, content={"document_id": doc_id, "status": "duplicate"}
                )
        job = json.dumps(
            {"document_id": doc_id, "kb_id": kb_id, "content_b64": content_b64, "source": source}
        ).encode()
        await bus.publish_durable(INGEST_SUBJECT, job)  # persisted job (H-3)
    return JSONResponse(status_code=202, content={"document_id": doc_id, "status": "queued"})


@app.get("/documents/{doc_id}", tags=["gateway"])
async def get_document(doc_id: str) -> JSONResponse:
    doc = await catalog.get_document(doc_id)
    return JSONResponse(status_code=200 if doc else 404, content=doc or {"error": "not found"})


_TERMINAL = ("done", "failed")


@app.get("/documents/{doc_id}/events", tags=["gateway"])
async def document_events(doc_id: str, request: Request) -> StreamingResponse:
    """Live ingestion feed over SSE (R-BE-7): a current-status snapshot, then this document's
    saga status + per-stage progress events as they arrive, so the SagaStepper advances in
    real time instead of polling. The stream closes on the terminal `done`/`failed` state, on
    an unknown document, or when the client disconnects."""
    queue = _register_listener(doc_id)

    async def gen() -> AsyncIterator[str]:
        idle = 0
        try:
            yield _sse("open", {"document_id": doc_id})
            # Snapshot: replay the current persisted state so a late subscriber isn't blank,
            # and so an already-finished (or unknown) document ends the stream immediately.
            doc = await catalog.get_document(doc_id)
            if doc is None:
                yield _sse("error", {"document_id": doc_id, "message": "unknown document"})
                return
            yield _sse("status", doc)
            if str(doc.get("status")) in _TERMINAL:
                return
            while not await request.is_disconnected():
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    idle += 1
                    if idle % 15 == 0:  # keep the connection warm through proxies (~15s)
                        yield ": keepalive\n\n"
                    continue
                idle = 0
                yield _sse("status", evt)
                if str(evt.get("status")) in _TERMINAL:
                    break  # terminal state — close the stream
        finally:
            _unregister_listener(doc_id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/documents/{doc_id}/confirm", tags=["gateway"])
async def confirm_document(doc_id: str, req: Request) -> dict[str, str]:
    """Confirm a paused (awaiting_confirm) document so ingestion resumes it (R9/R55, M-3).

    An optional `domain_id` in the body overrides the detected domain (the UI's "Change"),
    so the user's choice is pinned instead of the low-confidence detection (R-BE-8).
    """
    try:
        body = await req.json()
    except Exception:
        body = {}
    msg: dict[str, str] = {"document_id": doc_id}
    domain_id = (body or {}).get("domain_id")
    if domain_id:
        msg["domain_id"] = domain_id
    await bus.publish(CONFIRM_SUBJECT, json.dumps(msg).encode())
    return {"document_id": doc_id, "status": "confirming"}


@app.get("/kb/{kb_id}/stats", tags=["gateway"])
async def kb_stats(kb_id: str) -> dict[str, object]:
    return await call_get("graph", f"/stats/{kb_id}")


@app.post("/query", tags=["gateway"])
async def query(body: QueryRequest) -> dict[str, object]:
    payload = {"query": body.query, "kb_ids": body.scope()}
    with tracer("gateway").start_as_current_span("gateway.query"):
        return await call("query", "/answer", payload)


def _answer_tokens(text: str) -> list[str]:
    """Chunk verified answer text for server-side streaming, preserving exact bytes.

    `\\S+\\s*` keeps each word with its trailing whitespace, so concatenating the tokens
    reconstructs the original text character-for-character (core constraint #1: the stream
    is a presentation of the computed answer, never a different one)."""
    return re.findall(r"\S+\s*", text) or ([text] if text else [])


@app.post("/query/stream", tags=["gateway"])
async def query_stream(body: QueryRequest) -> StreamingResponse:
    """Stream the crew live over SSE (R35, R-BE-4): the four stage events in order, then —
    **only after the Critic approves** — the verified answer text token-by-token.

    Strict groundedness (R31/R32) is guaranteed by construction: `/answer` runs the whole
    crew (plan → retrieve → synthesize → critique) and returns a *fully verified* answer, so
    no unverified LLM prose can reach the browser. The Critic stage gates the token stream;
    the Synthesizer stage is the reveal of the already-verified text."""
    payload = {"kb_ids": body.scope(), "query": body.query}

    async def gen() -> AsyncIterator[str]:
        try:
            # Planner → Retriever run inside the single /answer call (R53). One backend call:
            # /answer retrieves once and returns the evidence it used, so we don't retrieve
            # twice and the `done` evidence matches the citations (R36, M-15).
            yield _sse("stage", {"stage": "planner", "state": "active"})
            yield _sse("stage", {"stage": "planner", "state": "done"})
            yield _sse("stage", {"stage": "retriever", "state": "active"})
            result = await call("query", "/answer", payload)
            answer = result.get("answer", {})
            evidence = result.get("evidence", {})
            yield _sse("stage", {"stage": "retriever", "state": "done"})

            # Critic gate: reflect the verdict the crew already produced. A refusal is a
            # `blocked` Critic (R31); an accepted answer is `ok` and unlocks the token stream.
            refused = bool(answer.get("refused"))
            yield _sse("stage", {"stage": "critic", "state": "active"})
            yield _sse(
                "stage",
                {"stage": "critic", "state": "blocked" if refused else "done",
                 "verdict": "refused" if refused else "ok",
                 "ungrounded_claims": answer.get("ungrounded_claims", [])},
            )

            # Synthesizer: reveal ONLY the verified text (or the honest refusal), chunked
            # server-side so the bytes match `answer.text` exactly.
            yield _sse("stage", {"stage": "synthesizer", "state": "active"})
            for tok in _answer_tokens(answer.get("text", "")):
                yield _sse("token", {"text": tok})
            yield _sse("stage", {"stage": "synthesizer", "state": "done"})
            yield _sse("done", {"answer": answer, "evidence": evidence})
        except Exception as exc:
            # Emit an error event so the UI stops spinning instead of hanging forever (M-15).
            log.warning("query stream failed: %s", exc)
            yield _sse("error", {"message": "the query failed — please retry"})

    return StreamingResponse(gen(), media_type="text/event-stream")
