"""Extraction service — domain detection + schema-driven extraction (R8, R16).

Owns the domain registry. P0: no-op shell returning the generic fallback.
"""

from __future__ import annotations

from fastapi import Request
from provenance_contracts import REGISTRY
from provenance_service import create_app, tracer

from .detection import detect, should_pause_for_confirmation

app = create_app("extraction")


@app.get("/domains", tags=["extraction"])
async def domains() -> dict[str, list[str]]:
    """Expose the registry shape (R15) — domains are data."""
    return {"domains": sorted(REGISTRY.keys())}


@app.post("/detect", tags=["extraction"])
async def detect_domain(req: Request) -> dict[str, object]:
    """Detect the document domain from a text sample (R8) + flag confirm need (R9)."""
    body = await req.json()
    text = body.get("text", "")
    with tracer("extraction").start_as_current_span("extraction.detect") as span:
        d = detect(text)
        span.set_attribute("detect.domain", d.domain)
        span.set_attribute("detect.confidence", d.confidence)
        return {**d.model_dump(), "needs_confirmation": should_pause_for_confirmation(d)}


@app.post("/extract", tags=["extraction"])
async def extract() -> dict[str, object]:
    with tracer("extraction").start_as_current_span("extraction.extract"):
        return {"ok": True, "entities": 0, "relations": 0, "note": "P0 skeleton no-op"}
