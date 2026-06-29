"""Parse service — layout-aware OCR / table extraction (R60–R64).

Digital-first parsing via pdfplumber (born-digital PDFs); OCR fallback via Docling +
PaddleOCR is loaded lazily for image-only pages (DGX Spark). Returns typed elements with
page + bbox + reading order, and records the parse method as provenance (R63).
"""

from __future__ import annotations

import base64

from fastapi import Request
from provenance_service import create_app, tracer

from .parse_engine import parse_pdf_bytes

app = create_app("parse")


@app.post("/parse", tags=["parse"])
async def parse(req: Request) -> dict[str, object]:
    """Parse a base64-encoded PDF into typed elements with geometry + provenance."""
    body = await req.json()
    content_b64 = body.get("content_b64", "")
    with tracer("parse").start_as_current_span("parse.document") as span:
        if not content_b64:
            # No payload (e.g. P0-style ping): return an empty, well-formed result.
            return {"elements": [], "pages": 0, "parse_method": "text_layer", "engine": "none"}
        result = parse_pdf_bytes(base64.b64decode(content_b64))
        span.set_attribute("parse.elements", len(result.elements))
        span.set_attribute("parse.method", result.parse_method.value)
        return result.model_dump()
