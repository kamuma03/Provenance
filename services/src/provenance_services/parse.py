"""Parse service — layout-aware OCR / table extraction (R60–R64).

Backend selected by PARSE_ENGINE (R60):
  * `docling` (default) — Docling document-understanding pipeline (layout + TableFormer +
    reading order) with PaddleOCR (RapidOCR ONNX) for raster pages.
  * `pdfplumber` — lightweight digital-first (pdfplumber) + RapidOCR fallback; air-gap-fast.
Both return typed elements with page + bbox + reading order and record provenance (R63).
"""

from __future__ import annotations

import base64
import os

from fastapi import Request
from provenance_contracts import ParseResult
from provenance_service import create_app, tracer

app = create_app("parse")


def parse_document(content: bytes) -> ParseResult:
    engine = os.environ.get("PARSE_ENGINE", "docling").lower()
    if engine.startswith("docling"):
        from .docling_parser import parse_pdf_bytes_docling
        return parse_pdf_bytes_docling(content)
    from .parse_engine import parse_pdf_bytes
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
        return result.model_dump()
