"""Extraction service — domain detection + schema-driven extraction (R8, R16).

Owns the domain registry. P0: no-op shell returning the generic fallback.
"""

from __future__ import annotations

from typing import cast

from provenance_contracts import GENERIC_FALLBACK_ID, REGISTRY
from provenance_service import create_app, get_llm, tracer, validate_routes
from pydantic import BaseModel

from .detection import detect, should_pause_for_confirmation
from .extraction_engine import extract as run_extract
from .extraction_engine import make_llm_extractor


async def _startup() -> None:
    validate_routes(["extraction", "detection"])  # fail fast on a route typo (M-14)


app = create_app("extraction", on_startup=_startup)


class DetectRequest(BaseModel):
    text: str = ""


class ExtractRequest(BaseModel):
    text: str = ""
    domain_id: str = GENERIC_FALLBACK_ID


@app.get("/domains", tags=["extraction"])
async def domains() -> dict[str, list[str]]:
    """Expose the registry shape (R15) — domains are data."""
    return {"domains": sorted(REGISTRY.keys())}


@app.post("/detect", tags=["extraction"])
async def detect_domain(body: DetectRequest) -> dict[str, object]:
    """Detect the document domain from a text sample (R8) + flag confirm need (R9)."""
    with tracer("extraction").start_as_current_span("extraction.detect") as span:
        d = detect(body.text)
        span.set_attribute("detect.domain", d.domain)
        span.set_attribute("detect.confidence", d.confidence)
        return {**d.model_dump(), "needs_confirmation": should_pause_for_confirmation(d)}


@app.post("/extract", tags=["extraction"])
async def extract_entities(body: ExtractRequest) -> dict[str, object]:
    """Schema-driven extraction for the given domain (R16). LLM path = Spark."""
    spec = REGISTRY.get(body.domain_id, REGISTRY[GENERIC_FALLBACK_ID])
    client = get_llm("extraction")  # local model on the Spark, or None → heuristic (A2)
    llm = make_llm_extractor(client) if client is not None else None
    with tracer("extraction").start_as_current_span("extraction.extract") as span:
        result = await run_extract(body.text, spec, llm)
        span.set_attribute("extract.entities", len(result.entities))
        span.set_attribute("extract.llm", client is not None)
        return cast("dict[str, object]", result.model_dump())
