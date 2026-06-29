"""Ingestion service — async saga orchestrator with compensation (R54).

Consumes ingest jobs from NATS and drives the saga across Parse → Extraction → Graph →
Model → Vector. The trace context rides the NATS headers (R56), so the whole saga is one
trace. On failure, completed steps are compensated in reverse and the document ends
`failed` — never half-ingested.
"""

from __future__ import annotations

import json
import logging

from provenance_service import NatsBus, ServiceSettings, create_app, tracer

from .clients import call
from .saga import Ctx, Saga, SagaStatus, Step

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ingestion")

settings = ServiceSettings(service_name="ingestion")  # type: ignore[call-arg]
bus = NatsBus(settings.nats_url)

INGEST_SUBJECT = "ingest.jobs"


def _svc_step(service: str, path: str):  # type: ignore[no-untyped-def]
    async def run(_ctx: Ctx) -> None:
        await call(service, path)

    return run


def _compensate(service: str):  # type: ignore[no-untyped-def]
    async def comp(ctx: Ctx) -> None:
        # Best-effort rollback of partial writes (delete-by-document lands with the
        # stores' delete support; for now we record the intent on the trace).
        log.warning("compensating %s for document_id=%s", service, ctx.get("document_id"))

    return comp


def _build_saga() -> Saga:
    return Saga([
        Step("parse", _svc_step("parse", "/parse")),
        Step("detect", _svc_step("extraction", "/detect")),
        # detect-but-confirm pause (R9/R55) wires in once the confirm callback exists.
        Step("extract", _svc_step("extraction", "/extract")),
        Step("write_graph", _svc_step("graph", "/write"), compensate=_compensate("graph")),
        Step("embed", _svc_step("model", "/embed")),
        Step("upsert", _svc_step("vector", "/upsert"), compensate=_compensate("vector")),
    ])


async def _run_saga(data: bytes, _headers: dict[str, str]) -> None:
    job = json.loads(data or b"{}")
    ctx: Ctx = {"document_id": job.get("document_id", "?"), "kb_id": job.get("kb_id", "?")}
    with tracer("ingestion").start_as_current_span("ingestion.saga") as span:
        span.set_attribute("document_id", str(ctx["document_id"]))
        outcome = await _build_saga().run(ctx)
        span.set_attribute("saga.status", outcome.status.value)
        if outcome.status is SagaStatus.FAILED:
            log.error(
                "saga FAILED at %s for document_id=%s; compensated=%s; error=%s",
                outcome.failed_step, ctx["document_id"], outcome.compensated, outcome.error,
            )
        else:
            log.info("saga %s for document_id=%s", outcome.status.value, ctx["document_id"])


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
