"""Ingestion service — async saga orchestrator with compensation (R54).

Consumes ingest jobs from NATS and drives the real saga: Parse → chunk → detect →
extract → write graph (Kuzu) → embed → upsert vectors (FAISS). The trace context rides
the NATS headers (R56), so the whole saga is one trace. On failure, completed steps
compensate in reverse and the document ends `failed`. Status events flow back to the
Gateway via NATS for catalog updates (B.4).
"""

from __future__ import annotations

import json
import logging
from typing import cast

from provenance_contracts import Chunk, ParsedElement
from provenance_service import NatsBus, ServiceSettings, create_app, tracer

from .chunker import chunk_elements
from .clients import call
from .saga import Ctx, Saga, SagaStatus, Step

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ingestion")

settings = ServiceSettings(service_name="ingestion")
bus = NatsBus(settings.nats_url)

INGEST_SUBJECT = "ingest.jobs"
STATUS_SUBJECT = "ingest.status"


def _compensate(service: str):  # type: ignore[no-untyped-def]
    async def comp(ctx: Ctx) -> None:
        log.warning("compensating %s for document_id=%s", service, ctx.get("document_id"))

    return comp


async def _parse_step(c: Ctx) -> None:
    resp = await call("parse", "/parse", {"content_b64": c.get("content_b64", "")})
    c["elements"] = [ParsedElement(**e) for e in resp.get("elements", [])]


async def _chunk_step(c: Ctx) -> None:
    elements = cast("list[ParsedElement]", c["elements"])
    c["chunks"] = chunk_elements(
        elements, document_id=str(c["document_id"]), kb_id=str(c["kb_id"])
    )


async def _detect_step(c: Ctx) -> None:
    chunks = cast("list[Chunk]", c["chunks"])
    sample = "\n".join(ch.text for ch in chunks)[:2000]
    c["sample"] = sample
    resp = await call("extraction", "/detect", {"text": sample})
    c["domain"] = resp.get("domain", "generic")


async def _extract_step(c: Ctx) -> None:
    payload = {"text": c.get("sample", ""), "domain_id": c["domain"]}
    resp = await call("extraction", "/extract", payload)
    c["entities"] = resp.get("entities", [])
    c["relations"] = resp.get("relations", [])


async def _graph_step(c: Ctx) -> None:
    await call("graph", "/write", {
        "kb_id": c["kb_id"], "document_id": c["document_id"],
        "entities": c["entities"], "relations": c["relations"], "trace_id": c.get("trace_id"),
    })


async def _embed_step(c: Ctx) -> None:
    chunks = cast("list[Chunk]", c["chunks"])
    texts = [ch.text for ch in chunks]
    resp = await call("model", "/embed", {"texts": texts})
    c["embeddings"] = resp.get("embeddings", [])


async def _vector_step(c: Ctx) -> None:
    chunks = cast("list[Chunk]", c["chunks"])
    embeddings = cast("list[list[float]]", c["embeddings"])
    records = [
        {"chunk_id": ch.id, "embedding": emb, "text": ch.text,
         "metadata": {
             "document_id": str(c["document_id"]), "page": str(ch.page),
             "bbox": ch.bbox.model_dump_json(),  # carried for citation highlight (R36)
         }}
        for ch, emb in zip(chunks, embeddings, strict=False)
    ]
    if records:
        await call("vector", "/upsert", {"namespace": c["kb_id"], "records": records})


def _build_saga() -> Saga:
    return Saga([
        Step("parse", _parse_step),
        Step("chunk", _chunk_step),
        Step("detect", _detect_step),
        Step("extract", _extract_step),
        Step("write_graph", _graph_step, compensate=_compensate("graph")),
        Step("embed", _embed_step),
        Step("upsert", _vector_step, compensate=_compensate("vector")),
    ])


async def _publish_status(document_id: str, status: str) -> None:
    payload = json.dumps({"document_id": document_id, "status": status}).encode()
    await bus.publish(STATUS_SUBJECT, payload)


async def _run_saga(data: bytes, _headers: dict[str, str]) -> None:
    job = json.loads(data or b"{}")
    doc_id = str(job.get("document_id", "?"))
    ctx: Ctx = {
        "document_id": doc_id,
        "kb_id": job.get("kb_id", "?"),
        "content_b64": job.get("content_b64", ""),
    }
    with tracer("ingestion").start_as_current_span("ingestion.saga") as span:
        ctx["trace_id"] = format(span.get_span_context().trace_id, "032x")
        span.set_attribute("document_id", doc_id)
        await _publish_status(doc_id, "parsing")
        outcome = await _build_saga().run(ctx)
        span.set_attribute("saga.status", outcome.status.value)
        if outcome.status is SagaStatus.FAILED:
            await _publish_status(doc_id, "failed")
            log.error("saga FAILED at %s for %s: %s", outcome.failed_step, doc_id, outcome.error)
        elif outcome.status is SagaStatus.DONE:
            await _publish_status(doc_id, "done")
            log.info("saga done for document_id=%s (domain=%s)", doc_id, ctx.get("domain"))


async def _on_startup() -> None:
    await bus.connect()
    await bus.subscribe(INGEST_SUBJECT, _run_saga, queue="ingestion")
    log.info("subscribed to %s", INGEST_SUBJECT)


async def _on_shutdown() -> None:
    await bus.close()


async def _ready() -> bool:
    return bus.connected


app = create_app(
    "ingestion", settings=settings, readiness=_ready,
    on_startup=_on_startup, on_shutdown=_on_shutdown,
)
