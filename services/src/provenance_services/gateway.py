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
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from provenance_service import NatsBus, ServiceSettings, create_app, tracer

from .catalog import Catalog
from .clients import call, call_get


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

settings = ServiceSettings(service_name="gateway")
bus = NatsBus(settings.nats_url)
catalog = Catalog()

INGEST_SUBJECT = "ingest.jobs"
STATUS_SUBJECT = "ingest.status"


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
async def create_kb(req: Request) -> dict[str, str]:
    body = await req.json()
    kb_id = f"kb_{uuid.uuid4().hex[:8]}"
    await catalog.create_kb(kb_id, body.get("name", "untitled"), body.get("domain_id", "generic"))
    return {"id": kb_id}


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
        await bus.publish(INGEST_SUBJECT, job)
    return JSONResponse(status_code=202, content={"document_id": doc_id, "status": "queued"})


@app.get("/documents/{doc_id}", tags=["gateway"])
async def get_document(doc_id: str) -> JSONResponse:
    doc = await catalog.get_document(doc_id)
    return JSONResponse(status_code=200 if doc else 404, content=doc or {"error": "not found"})


@app.get("/kb/{kb_id}/stats", tags=["gateway"])
async def kb_stats(kb_id: str) -> dict[str, object]:
    return await call_get("graph", f"/stats/{kb_id}")


@app.post("/query", tags=["gateway"])
async def query(req: Request) -> dict[str, object]:
    body = await req.json()
    payload = {"query": body.get("query", ""), "kb_id": body.get("kb_id", "default")}
    with tracer("gateway").start_as_current_span("gateway.query"):
        return await call("query", "/answer", payload)


@app.post("/query/stream", tags=["gateway"])
async def query_stream(req: Request) -> StreamingResponse:
    """Stream the answer over SSE (R35): status → tokens → done{answer, evidence}."""
    body = await req.json()
    kb_id = body.get("kb_id", "default")
    query_text = body.get("query", "")
    payload = {"kb_id": kb_id, "query": query_text}

    async def gen() -> AsyncIterator[str]:
        yield _sse("status", {"phase": "retrieving"})
        evidence = await call("query", "/retrieve", payload)  # chunks + entity_ids (R37/R36)
        yield _sse("status", {"phase": "synthesizing"})
        result = await call("query", "/answer", payload)
        answer = result.get("answer", {})
        if answer.get("refused"):
            yield _sse("token", {"text": answer.get("text", "")})
        else:
            for word in answer.get("text", "").split():
                yield _sse("token", {"text": word + " "})
        yield _sse("done", {"answer": answer, "evidence": evidence})

    return StreamingResponse(gen(), media_type="text/event-stream")
