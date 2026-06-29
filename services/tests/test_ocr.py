"""OCR fallback test (R60–R63) — a genuinely image-only PDF is read via OCR.

Builds a PDF whose only content is a rasterized image of text (no text layer), so the
digital-first path finds nothing and the OCR fallback must produce the text + bboxes.
"""

from __future__ import annotations

import io

import pytest
from provenance_contracts import ParseMethod

pytest.importorskip("reportlab")
pytest.importorskip("rapidocr_onnxruntime")

from PIL import Image, ImageDraw  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.utils import ImageReader  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402


def _image_only_pdf(text: str) -> bytes:
    img = Image.new("RGB", (900, 200), "white")
    ImageDraw.Draw(img).text((30, 80), text, fill="black")
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)

    pdf_buf = io.BytesIO()
    c = canvas.Canvas(pdf_buf, pagesize=letter)
    c.drawImage(ImageReader(img_buf), 40, 500, width=500, height=110)  # image only, no text layer
    c.showPage()
    c.save()
    return pdf_buf.getvalue()


def test_image_only_pdf_is_read_via_ocr() -> None:
    from provenance_services.parse_engine import parse_pdf_bytes

    pdf = _image_only_pdf("Auditor Ernst and Young")
    result = parse_pdf_bytes(pdf, enable_ocr=True)

    assert result.parse_method is ParseMethod.OCR
    assert "rapidocr" in result.engine
    blob = " ".join(e.text for e in result.elements).lower()
    assert "ernst" in blob or "auditor" in blob  # OCR recovered the text
    for e in result.elements:  # OCR elements carry real geometry (R60)
        assert e.bbox.x1 >= e.bbox.x0 and e.bbox.y1 >= e.bbox.y0


def test_ocr_can_be_disabled() -> None:
    from provenance_services.parse_engine import parse_pdf_bytes

    pdf = _image_only_pdf("Auditor Ernst and Young")
    result = parse_pdf_bytes(pdf, enable_ocr=False)
    assert result.elements == []  # no text layer, OCR off => nothing extracted
    assert result.engine == "pdfplumber"
