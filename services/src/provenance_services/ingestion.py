"""Ingestion service — async saga orchestrator with compensation (R54).

Consumes ingest jobs from NATS and drives the real saga: Parse → chunk → detect →
extract → write graph (Kuzu) → embed → upsert vectors (FAISS). The trace context rides
the NATS headers (R56), so the whole saga is one trace. On failure, completed steps
compensate in reverse and the document ends `failed`. Status events flow back to the
Gateway via NATS for catalog updates (B.4).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from collections.abc import Iterator
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
INGEST_STREAM = "INGEST"

# Domain detection needs only a sample; extraction must cover the WHOLE document, batched
# into windows through the cheap LLM tier so entities/relations past page ~2 reach the graph
# (review H-1). One window per ~this-many characters bounds the number of extract calls.
_DETECT_SAMPLE_CHARS = int(os.environ.get("DETECT_SAMPLE_CHARS", "2000"))
_EXTRACT_WINDOW_CHARS = int(os.environ.get("EXTRACT_WINDOW_CHARS", "4000"))


def _windows(chunks: list[Chunk], size: int) -> Iterator[str]:
    """Group consecutive chunk texts into windows of at most `size` characters."""
    buf: list[str] = []
    length = 0
    for ch in chunks:
        if buf and length + len(ch.text) > size:
            yield "\n".join(buf)
            buf, length = [], 0
        buf.append(ch.text)
        length += len(ch.text)
    if buf:
        yield "\n".join(buf)


def _compensate(service: str):  # type: ignore[no-untyped-def]
    """Real rollback (R54, review H-3): call the owning service's delete-by-document endpoint
    so a failed saga leaves no orphaned vectors/entities. Best-effort — a compensation error
    is logged, never raised, so the saga still reaches a terminal `failed`."""
    async def comp(ctx: Ctx) -> None:
        doc_id = str(ctx.get("document_id"))
        try:
            if service == "graph":
                await call("graph", "/delete", {"document_id": doc_id})
            elif service == "vector":
                await call(
                    "vector", "/delete",
                    {"namespace": ctx.get("kb_id"), "document_id": doc_id},
                )
            log.info("compensated %s for document_id=%s", service, doc_id)
        except Exception as exc:  # noqa: BLE001 - rollback is best-effort
            log.warning("compensation for %s failed for %s: %s", service, doc_id, exc)

    return comp


async def _parse_step(c: Ctx) -> None:
    resp = await call("parse", "/parse", {"content_b64": c.get("content_b64", "")})
    c["elements"] = [ParsedElement(**e) for e in resp.get("elements", [])]
    # Capture parse provenance for the Document row (R56/R63, review H-9).
    c["parse_method"] = resp.get("parse_method")
    if resp.get("parse_method") == "ocr":
        c["ocr_engine"] = resp.get("engine")


async def _chunk_step(c: Ctx) -> None:
    elements = cast("list[ParsedElement]", c["elements"])
    c["chunks"] = chunk_elements(
        elements, document_id=str(c["document_id"]), kb_id=str(c["kb_id"])
    )


async def _detect_step(c: Ctx) -> None:
    await _publish_status(str(c["document_id"]), "detecting")
    chunks = cast("list[Chunk]", c["chunks"])
    sample = "\n".join(ch.text for ch in chunks)[:_DETECT_SAMPLE_CHARS]
    c["sample"] = sample
    resp = await call("extraction", "/detect", {"text": sample})
    c["domain"] = resp.get("domain", "generic")
    c["detection_confidence"] = resp.get("confidence")


async def _extract_step(c: Ctx) -> None:
    # Extract over the whole document (windowed), not just the detection sample — otherwise
    # entities/relations beyond the first ~2000 chars never reach the graph (review H-1).
    await _publish_status(str(c["document_id"]), "extracting")
    chunks = cast("list[Chunk]", c["chunks"])
    entities: list[dict[str, object]] = []
    relations: list[dict[str, object]] = []
    seen_e: set[tuple[object, ...]] = set()
    seen_r: set[tuple[object, ...]] = set()
    for window in _windows(chunks, _EXTRACT_WINDOW_CHARS):
        resp = await call("extraction", "/extract", {"text": window, "domain_id": c["domain"]})
        c["schema_version"] = resp.get("schema_version")
        for e in resp.get("entities", []):
            ekey = (e.get("type"), e.get("canonical_name"))
            if ekey not in seen_e:
                seen_e.add(ekey)
                entities.append(e)
        for r in resp.get("relations", []):
            rkey = (r.get("subject"), r.get("predicate"), r.get("object"))
            if rkey not in seen_r:
                seen_r.add(rkey)
                relations.append(r)
    c["entities"] = entities
    c["relations"] = relations


async def _graph_step(c: Ctx) -> None:
    await call("graph", "/write", {
        "kb_id": c["kb_id"], "document_id": c["document_id"],
        "entities": c["entities"], "relations": c["relations"], "trace_id": c.get("trace_id"),
    })


async def _embed_step(c: Ctx) -> None:
    await _publish_status(str(c["document_id"]), "embedding")
    chunks = cast("list[Chunk]", c["chunks"])
    texts = [ch.text for ch in chunks]
    resp = await call("model", "/embed", {"texts": texts})
    c["embeddings"] = resp.get("embeddings", [])
    c["embedding_model_id"] = resp.get("model_id")  # namespace model-id guard (R66, H-7)


async def _vector_step(c: Ctx) -> None:
    chunks = cast("list[Chunk]", c["chunks"])
    embeddings = cast("list[list[float]]", c["embeddings"])
    records = [
        {"chunk_id": ch.id, "embedding": emb, "text": ch.text,
         "metadata": {
             "document_id": str(c["document_id"]), "page": str(ch.page),
             "bbox": ch.bbox.model_dump_json(),  # carried for citation highlight (R36)
         }}
        # strict=True: an embeddings/chunks count mismatch must fail the saga, not silently
        # drop trailing chunks from the index while reporting done (review M-10).
        for ch, emb in zip(chunks, embeddings, strict=True)
    ]
    if records:
        await call("vector", "/upsert", {
            "namespace": c["kb_id"], "records": records,
            "model_id": c.get("embedding_model_id"),
        })


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


def _provenance(c: Ctx) -> dict[str, object]:
    """The provenance payload persisted on the Document row (R56/R63, review H-9)."""
    prov = {
        "detected_domain": c.get("domain"),
        "detection_confidence": c.get("detection_confidence"),
        "schema_version": c.get("schema_version"),
        "parse_method": c.get("parse_method"),
        "ocr_engine": c.get("ocr_engine"),
        "trace_id": c.get("trace_id"),
    }
    return {k: v for k, v in prov.items() if v is not None}


async def _publish_status(
    document_id: str, status: str, provenance: dict[str, object] | None = None
) -> None:
    evt: dict[str, object] = {"document_id": document_id, "status": status}
    if provenance:
        evt["provenance"] = provenance
    await bus.publish(STATUS_SUBJECT, json.dumps(evt).encode())


async def _run_saga(data: bytes, _headers: dict[str, str]) -> None:
    # Failure containment (review M-11): nothing here may escape the consumer callback, or a
    # malformed job / status-publish error would strand the document in a non-terminal state
    # (and, under the durable consumer, loop forever on the poison message). Everything is
    # wrapped; a caught error is logged against the document id and best-effort published.
    doc_id = "?"
    try:
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
                log.error("saga FAILED at %s for %s: %s",
                          outcome.failed_step, doc_id, outcome.error)
            elif outcome.status is SagaStatus.PAUSED:
                # detect-but-confirm (R9/R55): the saga parked for confirmation. Report it so
                # the document isn't silently stuck with no status. The interactive resume flow
                # is deferred — see docs/plans/remediation-plan.md (M-3).
                await _publish_status(doc_id, "awaiting_confirm")
                log.info("saga PAUSED at %s for %s (awaiting confirmation)",
                         outcome.failed_step, doc_id)
            elif outcome.status is SagaStatus.DONE:
                await _publish_status(doc_id, "done", _provenance(ctx))
                log.info("saga done for document_id=%s (domain=%s)", doc_id, ctx.get("domain"))
    except Exception:
        log.exception("ingestion callback error for document_id=%s", doc_id)
        with contextlib.suppress(Exception):
            await _publish_status(doc_id, "failed")


async def _on_startup() -> None:
    await bus.connect()
    # Durable consumer: ack only after the saga finishes, so an ingestion crash mid-saga
    # redelivers the job instead of stranding the document at queued/parsing (H-3).
    await bus.ensure_stream(INGEST_STREAM, [INGEST_SUBJECT])
    await bus.subscribe_durable(INGEST_SUBJECT, _run_saga, durable="ingestion", queue="ingestion")
    log.info("subscribed (durable) to %s", INGEST_SUBJECT)


async def _on_shutdown() -> None:
    await bus.close()


async def _ready() -> bool:
    return bus.connected


app = create_app(
    "ingestion", settings=settings, readiness=_ready,
    on_startup=_on_startup, on_shutdown=_on_shutdown,
)
