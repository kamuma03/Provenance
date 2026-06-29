"""Gateway / BFF — the REST/SSE edge + ingestion-saga entry point (R51, R53, R54).

Owns the Catalog. Accepts uploads (no-op in P0), enqueues an ingest job on NATS, and
proxies queries to the Query/Agent service. The async ingestion path returns 202 quickly.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from provenance_service import NatsBus, ServiceSettings, create_app, tracer

from .catalog import Catalog
from .clients import call

settings = ServiceSettings(service_name="gateway")  # type: ignore[call-arg]
bus = NatsBus(settings.nats_url)
catalog = Catalog()

INGEST_SUBJECT = "ingest.jobs"


async def _on_startup() -> None:
    await bus.connect()
    await catalog.connect()


async def _on_shutdown() -> None:
    await bus.close()
    await catalog.close()


async def _ready() -> bool:
    # Ready when the bus is up; catalog degrades gracefully (N6).
    return bus.connected


app = create_app(
    "gateway",
    settings=settings,
    readiness=_ready,
    on_startup=_on_startup,
    on_shutdown=_on_shutdown,
)


@app.post("/kb", tags=["gateway"])
async def create_kb(req: Request) -> dict[str, str]:
    body = await req.json()
    kb_id = f"kb_{uuid.uuid4().hex[:8]}"
    await catalog.create_kb(kb_id, body.get("name", "untitled"), body.get("domain_id", "generic"))
    return {"id": kb_id}


@app.post("/kb/{kb_id}/documents", tags=["gateway"])
async def upload_document(kb_id: str, req: Request) -> JSONResponse:
    """No-op upload (R5): persist queued Document, enqueue saga job, return 202."""
    body = await req.json()
    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    source = body.get("source", "unknown")
    content = (body.get("content") or source).encode()
    content_hash = hashlib.sha256(content).hexdigest()  # idempotency key (N5)
    with tracer("gateway").start_as_current_span("gateway.upload"):
        await catalog.create_document(
            doc_id, kb_id, source, "application/octet-stream", content_hash
        )
        job = json.dumps({"document_id": doc_id, "kb_id": kb_id}).encode()
        await bus.publish(INGEST_SUBJECT, job)
    return JSONResponse(status_code=202, content={"document_id": doc_id, "status": "queued"})


@app.post("/query", tags=["gateway"])
async def query(req: Request) -> dict[str, object]:
    body = await req.json()
    with tracer("gateway").start_as_current_span("gateway.query"):
        return await call("query", "/answer", {"query": body.get("query", "")})
