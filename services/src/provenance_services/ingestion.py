"""Ingestion service — async saga orchestrator (R54).

Consumes ingest jobs from NATS and drives the no-op saga across Parse → Extraction →
Graph → Model → Vector. The trace context rides the NATS headers (R56), so the whole
saga is one trace. Compensation + real steps land in P1.
"""

from __future__ import annotations

import json
import logging

from provenance_service import NatsBus, ServiceSettings, create_app, tracer

from .clients import call

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ingestion")

settings = ServiceSettings(service_name="ingestion")  # type: ignore[call-arg]
bus = NatsBus(settings.nats_url)

INGEST_SUBJECT = "ingest.jobs"


async def _run_saga(data: bytes, _headers: dict[str, str]) -> None:
    """No-op walking-skeleton saga. Real steps + compensation land in P1 (R54)."""
    job = json.loads(data or b"{}")
    doc_id = job.get("document_id", "?")
    with tracer("ingestion").start_as_current_span("ingestion.saga") as span:
        span.set_attribute("document_id", doc_id)
        await call("parse", "/parse")              # 1. parse (R60)
        await call("extraction", "/detect")        # 2. detect domain (R8)
        # 3. detect-but-confirm saga pause (R9/R55) — skipped in P0 no-op
        await call("extraction", "/extract")       # 4. extract (R16)
        await call("graph", "/write")              # 5. resolve + write graph (R18)
        await call("model", "/embed")              # 6a. embed
        await call("vector", "/upsert")            # 6b. write vectors
        log.info("saga complete (no-op) for document_id=%s", doc_id)


async def _on_startup() -> None:
    await bus.connect()
    await bus.subscribe(INGEST_SUBJECT, _run_saga, queue="ingestion")
    log.info("subscribed to %s", INGEST_SUBJECT)


async def _on_shutdown() -> None:
    await bus.close()


async def _ready() -> bool:
    return bus.connected


app = create_app(
    "ingestion",
    settings=settings,
    readiness=_ready,
    on_startup=_on_startup,
    on_shutdown=_on_shutdown,
)
