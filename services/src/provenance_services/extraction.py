"""Extraction service — domain detection + schema-driven extraction (R8, R16).

Owns the domain registry. P0: no-op shell returning the generic fallback.
"""

from __future__ import annotations

from fastapi import Request
from provenance_contracts import GENERIC_FALLBACK_ID, REGISTRY
from provenance_service import create_app, get_llm, tracer

from .detection import detect, should_pause_for_confirmation
from .extraction_engine import extract as run_extract
from .extraction_engine import make_llm_extractor

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
async def extract_entities(req: Request) -> dict[str, object]:
    """Schema-driven extraction for the given domain (R16). LLM path = Spark."""
    body = await req.json()
    text = body.get("text", "")
    domain_id = body.get("domain_id", GENERIC_FALLBACK_ID)
    spec = REGISTRY.get(domain_id, REGISTRY[GENERIC_FALLBACK_ID])
    client = get_llm("extraction")  # local model on the Spark, or None → heuristic (A2)
    llm = make_llm_extractor(client) if client is not None else None
    with tracer("extraction").start_as_current_span("extraction.extract") as span:
        result = await run_extract(text, spec, llm)
        span.set_attribute("extract.entities", len(result.entities))
        span.set_attribute("extract.llm", client is not None)
        return result.model_dump()
