"""Gateway / BFF — the REST/SSE edge + ingestion-saga entry point (R51, R53, R54).

Owns the Catalog. Accepts uploads (base64 content), enqueues an ingest job on NATS, and
proxies queries to Query/Agent. Subscribes to saga status events and writes Document
status transitions to the catalog (B.4). Returns 202 quickly on the async ingest path.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
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


async def _on_status(data: bytes, _headers: dict[str, str]) -> None:
    evt = json.loads(data or b"{}")
    doc_id, status = evt.get("document_id"), evt.get("status")
    if not (doc_id and status):
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


@app.post("/query/stream", tags=["gateway"])
async def query_stream(body: QueryRequest) -> StreamingResponse:
    """Stream the answer over SSE (R35): status → tokens → done{answer, evidence}."""
    payload = {"kb_ids": body.scope(), "query": body.query}

    async def gen() -> AsyncIterator[str]:
        try:
            yield _sse("status", {"phase": "retrieving"})
            # One backend call: /answer retrieves once and returns the evidence it used, so we
            # don't retrieve twice and the `done` evidence matches the citations (R36, M-15).
            result = await call("query", "/answer", payload)
            answer = result.get("answer", {})
            evidence = result.get("evidence", {})
            yield _sse("status", {"phase": "synthesizing"})
            if answer.get("refused"):
                yield _sse("token", {"text": answer.get("text", "")})
            else:
                for word in answer.get("text", "").split():
                    yield _sse("token", {"text": word + " "})
            yield _sse("done", {"answer": answer, "evidence": evidence})
        except Exception as exc:
            # Emit an error event so the UI stops spinning instead of hanging forever (M-15).
            log.warning("query stream failed: %s", exc)
            yield _sse("error", {"message": "the query failed — please retry"})

    return StreamingResponse(gen(), media_type="text/event-stream")
