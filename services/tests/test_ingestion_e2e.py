"""Full-ingestion integration test: OCR → chunk → local-LLM extraction.

Drives the real ingestion spine end to end with a genuinely *scanned* (image-only) PDF —
so the OCR fallback must run — and a local open-source model served over an OpenAI-
compatible API (Ollama / vLLM). It is gated on a reachable local LLM endpoint, so it's a
skip in the default offline suite and runs wherever a local model is up (the DGX Spark, or
any host after `scripts/start.sh --llm`).

Run it:
    LLM_LOCAL_BASE_URL=http://localhost:11434/v1 PROVENANCE_TEST_LLM_MODEL=qwen3.5:9b \
        uv run pytest services/tests/test_ingestion_e2e.py -v
"""

from __future__ import annotations

import io
import os

import pytest

pytest.importorskip("reportlab")
pytest.importorskip("rapidocr_onnxruntime")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.utils import ImageReader  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

SCANNED_TEXT = "Acme Robotics Inc reported annual revenue of 4.2 billion dollars"


def _scanned_pdf(text: str) -> bytes:
    """A PDF whose only content is a rasterized image of text — no text layer, so the
    digital-first path finds nothing and OCR must recover it."""
    img = Image.new("RGB", (1500, 240), "white")
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    try:  # a real TrueType face makes the raster OCR-friendly; fall back to the bitmap font
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except Exception:
        font = ImageFont.load_default()
    ImageDraw.Draw(img).text((30, 95), text, fill="black", font=font)
    png = io.BytesIO()
    img.save(png, format="PNG")
    png.seek(0)

    pdf = io.BytesIO()
    c = canvas.Canvas(pdf, pagesize=letter)
    c.drawImage(ImageReader(png), 36, 470, width=540, height=86)  # image only, no text layer
    c.showPage()
    c.save()
    return pdf.getvalue()


def _local_client():  # type: ignore[no-untyped-def]
    """Resolve a live local LLM client, skipping the test if none is reachable."""
    base = os.environ.get("LLM_LOCAL_BASE_URL")
    if not base:
        pytest.skip("LLM_LOCAL_BASE_URL not set — local-LLM ingestion test skipped")

    import httpx
    from provenance_service.llm import OpenAICompatLLMClient

    try:  # /v1/models is exposed by both Ollama and vLLM — provider-agnostic probe
        resp = httpx.get(f"{base.rstrip('/')}/models", timeout=4.0)
        resp.raise_for_status()
    except Exception as exc:  # endpoint configured but down → skip, don't fail the suite
        pytest.skip(f"local LLM endpoint unreachable at {base}: {exc}")

    model = os.environ.get("PROVENANCE_TEST_LLM_MODEL", "qwen3.5:9b")
    return OpenAICompatLLMClient(base, model)


@pytest.mark.asyncio
async def test_full_ingestion_ocr_then_local_llm_extraction() -> None:
    from provenance_contracts import REGISTRY, ParseMethod
    from provenance_services.chunker import chunk_elements
    from provenance_services.extraction_engine import extract, make_llm_extractor
    from provenance_services.parse_engine import parse_pdf_bytes

    client = _local_client()

    # 1) OCR — a genuinely scanned page is read by RapidOCR (no text layer to lean on).
    pdf = _scanned_pdf(SCANNED_TEXT)
    parsed = parse_pdf_bytes(pdf, enable_ocr=True)
    assert parsed.parse_method is ParseMethod.OCR
    assert "rapidocr" in parsed.engine
    ocr_text = " ".join(e.text for e in parsed.elements)
    assert any(k in ocr_text.lower() for k in ("acme", "robotics", "revenue")), ocr_text
    for e in parsed.elements:  # OCR elements carry real geometry (R60)
        assert e.bbox.x1 >= e.bbox.x0 and e.bbox.y1 >= e.bbox.y0

    # 2) chunk the OCR'd elements (prose here; tables would stay whole — R68).
    chunks = chunk_elements(parsed.elements, document_id="doc-1", kb_id="kb-1")
    assert chunks and any(c.text.strip() for c in chunks)
    chunk_text = "\n".join(c.text for c in chunks)

    # 3) extraction via the LOCAL model, validated against the domain schema (R16).
    spec = REGISTRY["sec_financial"]
    result = await extract(chunk_text, spec, make_llm_extractor(client))
    assert result.domain_id == "sec_financial"
    assert result.schema_version
    assert isinstance(result.entities, list)
    allowed = set(spec.entity_types)
    assert all(e.type in allowed for e in result.entities)  # off-schema repaired-by-dropping

    # 4) prove the local model was genuinely exercised (a non-empty completion came back).
    direct = await client.complete(
        "Reply with the company name only.", f"Which company is named here? {ocr_text}"
    )
    assert direct.strip(), "local LLM returned an empty completion"
