"""Ingestion saga unit tests (R54) — pure helpers, no network."""

from __future__ import annotations

import pytest
from provenance_contracts import BBox, Chunk
from provenance_services import ingestion
from provenance_services.ingestion import _EXTRACT_WINDOW_CHARS, _windows


def _chunk(cid: str, text: str) -> Chunk:
    return Chunk(
        id=cid, document_id="d1", kb_id="kb1", text=text, page=0,
        bbox=BBox(page=0, x0=0, y0=0, x1=1, y1=1), reading_order=0,
    )


def test_windows_cover_the_whole_document_not_just_the_detection_sample() -> None:
    # ~6000 chars of content, well past the 2000-char detection sample. Extraction must see
    # entities near the end of the document, not only the first window (review H-1).
    filler = "appears in the disclosure with additional surrounding context and boilerplate. "
    chunks = [_chunk(f"c{i}", f"entity{i} {filler}") for i in range(60)]
    total_chars = sum(len(c.text) for c in chunks)
    assert total_chars > 5000

    windows = list(_windows(chunks, _EXTRACT_WINDOW_CHARS))
    joined = "\n".join(windows)
    assert "entity0" in joined  # start of doc covered
    assert "entity59" in joined  # end of doc covered — the H-1 regression


def test_windows_are_bounded_in_size() -> None:
    chunks = [_chunk(f"c{i}", "x" * 500) for i in range(20)]
    windows = list(_windows(chunks, 1000))
    # Each window packs whole chunks up to the budget; a single chunk may exceed it but the
    # window never accumulates unboundedly.
    assert len(windows) >= 10
    assert all(len(w) <= 1000 + 500 for w in windows)


def test_windows_of_empty_document_is_empty() -> None:
    assert list(_windows([], _EXTRACT_WINDOW_CHARS)) == []


def test_provenance_payload_carries_trace_id_and_drops_nulls() -> None:
    # The Document row must store the correlating trace_id (R56 acceptance criterion); fields
    # not produced (here, ocr_engine on a text-layer doc) are omitted, not written as NULL noise.
    from provenance_services.ingestion import _provenance

    ctx = {
        "domain": "sec_financial", "detection_confidence": 0.91, "schema_version": "1.0",
        "parse_method": "text_layer", "trace_id": "abc123",
    }
    prov = _provenance(ctx)
    assert prov["detected_domain"] == "sec_financial"
    assert prov["detection_confidence"] == 0.91
    assert prov["parse_method"] == "text_layer"
    assert prov["trace_id"] == "abc123"  # R56 / H-9
    assert "ocr_engine" not in prov  # None-valued fields dropped


@pytest.mark.asyncio
async def test_malformed_job_does_not_escape_the_consumer_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A malformed job must not raise out of the NATS callback (which would loop forever on the
    # durable consumer) — it is contained, logged, and best-effort published failed (review M-11).
    published: list[tuple[str, str]] = []

    async def fake_publish(subject, payload):  # type: ignore[no-untyped-def]
        import json
        evt = json.loads(payload)
        published.append((evt["document_id"], evt["status"]))

    monkeypatch.setattr(ingestion.bus, "publish", fake_publish)

    await ingestion._run_saga(b"this is not json{{{", {})  # must not raise
    assert ("?", "failed") in published  # contained and reported
