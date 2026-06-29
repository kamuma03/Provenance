"""Parse service — layout-aware OCR / table extraction (R60–R64).

P0: no-op shell. Real Docling + PaddleOCR pipeline lands in P1.
"""

from __future__ import annotations

from provenance_service import create_app, tracer

app = create_app("parse")


@app.post("/parse", tags=["parse"])
async def parse() -> dict[str, object]:
    with tracer("parse").start_as_current_span("parse.document"):
        return {"ok": True, "elements": 0, "note": "P0 skeleton no-op"}
