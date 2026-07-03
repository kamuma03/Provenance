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
import os
from typing import cast

from fastapi import Request
from provenance_contracts import ParseResult
from provenance_service import create_app, tracer

app = create_app("parse")


def parse_document(content: bytes) -> ParseResult:
    from .parse_engine import needs_deep_parse, parse_pdf_bytes

    engine = os.environ.get("PARSE_ENGINE", "auto").lower()
    if engine == "auto":
        engine = "docling" if needs_deep_parse(content) else "pdfplumber"
    if engine.startswith("docling"):
        try:
            from .docling_parser import parse_pdf_bytes_docling
            return parse_pdf_bytes_docling(content)
        except Exception:  # docling unavailable (light deployment) → fall back
            return parse_pdf_bytes(content)
    return parse_pdf_bytes(content)


@app.post("/parse", tags=["parse"])
async def parse(req: Request) -> dict[str, object]:
    """Parse a base64-encoded PDF into typed elements with geometry + provenance."""
    body = await req.json()
    content_b64 = body.get("content_b64", "")
    with tracer("parse").start_as_current_span("parse.document") as span:
        if not content_b64:
            # No payload (e.g. P0-style ping): return an empty, well-formed result.
            return {"elements": [], "pages": 0, "parse_method": "text_layer", "engine": "none"}
        result = parse_document(base64.b64decode(content_b64))
        span.set_attribute("parse.elements", len(result.elements))
        span.set_attribute("parse.engine", result.engine)
        return cast("dict[str, object]", result.model_dump())
