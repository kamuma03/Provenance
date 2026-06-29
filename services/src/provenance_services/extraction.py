"""Extraction service — domain detection + schema-driven extraction (R8, R16).

Owns the domain registry. P0: no-op shell returning the generic fallback.
"""

from __future__ import annotations

from provenance_contracts import GENERIC_FALLBACK_ID, REGISTRY
from provenance_service import create_app, tracer

app = create_app("extraction")


@app.get("/domains", tags=["extraction"])
async def domains() -> dict[str, list[str]]:
    """Expose the registry shape (R15) — domains are data."""
    return {"domains": sorted(REGISTRY.keys())}


@app.post("/detect", tags=["extraction"])
async def detect() -> dict[str, object]:
    with tracer("extraction").start_as_current_span("extraction.detect"):
        # P0: real classifier (confidence + rationale) lands in P1.
        return {"domain": GENERIC_FALLBACK_ID, "confidence": 0.0, "rationale": "P0 no-op"}


@app.post("/extract", tags=["extraction"])
async def extract() -> dict[str, object]:
    with tracer("extraction").start_as_current_span("extraction.extract"):
        return {"ok": True, "entities": 0, "relations": 0, "note": "P0 skeleton no-op"}
