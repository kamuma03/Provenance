"""Gateway / BFF — the REST/SSE edge + ingestion-saga entry point (R51, R53, R54).

Owns the Catalog. Accepts uploads (base64 content), enqueues an ingest job on NATS, and
proxies queries to Query/Agent. Subscribes to saga status events and writes Document
status transitions to the catalog (B.4). Returns 202 quickly on the async ingest path.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from provenance_service import NatsBus, ServiceSettings, create_app, tracer

from .catalog import Catalog
from .clients import call, call_get

settings = ServiceSettings(service_name="gateway")  # type: ignore[call-arg]
bus = NatsBus(settings.nats_url)
catalog = Catalog()

INGEST_SUBJECT = "ingest.jobs"
STATUS_SUBJECT = "ingest.status"


async def _on_status(data: bytes, _headers: dict[str, str]) -> None:
    evt = json.loads(data or b"{}")
    if evt.get("document_id") and evt.get("status"):
        await catalog.update_status(evt["document_id"], evt["status"])


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
    content_hash = hashlib.sha256(base64.b64decode(content_b64)).hexdigest()  # idempotency (N5)
    with tracer("gateway").start_as_current_span("gateway.upload"):
        await catalog.create_document(
            doc_id, kb_id, source, "application/octet-stream", content_hash
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
