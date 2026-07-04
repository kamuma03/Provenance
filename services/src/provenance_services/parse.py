"""Parse service — layout-aware OCR / table extraction (R60–R64).

Backend selected by PARSE_ENGINE (R60):
  * `auto` (default) — a cheap probe routes each document: scanned or table-heavy → the
    deep Docling path (layout + TableFormer + PaddleOCR, GPU-capable); clean prose →
    the fast pdfplumber + RapidOCR path. "Deep parse only when it's worth it."
  * `docling` — always the deep pipeline.
  * `pdfplumber` — always the lightweight digital-first path; air-gap-fast.
Both return typed elements with page + bbox + reading order and record provenance (R63).
"""

from __future__ import annotations

import base64
import logging
import os
from typing import cast

import anyio
from provenance_contracts import ParseResult
from provenance_service import create_app, tracer
from pydantic import BaseModel

log = logging.getLogger("parse")
app = create_app("parse")


class ParseRequest(BaseModel):
    content_b64: str = ""


def parse_document(content: bytes) -> ParseResult:
    from .parse_engine import needs_deep_parse, parse_pdf_bytes

    engine = os.environ.get("PARSE_ENGINE", "auto").lower()
    if engine == "auto":
        engine = "docling" if needs_deep_parse(content) else "pdfplumber"
    if engine.startswith("docling"):
        try:
            from .docling_parser import parse_pdf_bytes_docling
            return parse_pdf_bytes_docling(content)
        except Exception as exc:
            # Docling unavailable (light deployment) or failed → fall back to pdfplumber, but
            # log it: a silent downgrade of the deep path shouldn't be invisible (review M-12).
            log.warning("docling parse failed, falling back to pdfplumber: %s", exc)
            return parse_pdf_bytes(content)
    return parse_pdf_bytes(content)


@app.post("/parse", tags=["parse"])
async def parse(body: ParseRequest) -> dict[str, object]:
    """Parse a base64-encoded PDF into typed elements with geometry + provenance."""
    content_b64 = body.content_b64
    with tracer("parse").start_as_current_span("parse.document") as span:
        if not content_b64:
            # No payload (e.g. P0-style ping): return an empty, well-formed result.
            return {"elements": [], "pages": 0, "parse_method": "text_layer", "engine": "none"}
        # A full Docling/OCR parse is seconds-to-minutes of CPU; keep it off the event loop
        # so liveness probes answer and one scanned doc can't stall the service (review H-5).
        result = await anyio.to_thread.run_sync(parse_document, base64.b64decode(content_b64))
        span.set_attribute("parse.elements", len(result.elements))
        span.set_attribute("parse.engine", result.engine)
        return cast("dict[str, object]", result.model_dump())
