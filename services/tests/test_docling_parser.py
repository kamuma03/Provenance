"""Docling parser test (R60-R63) — runs the real Docling pipeline if installed.

Skipped where Docling/models are unavailable (e.g. minimal CI); the pdfplumber+RapidOCR
backend is always tested. Verifies Docling output maps onto the ParseResult contract.
"""

from __future__ import annotations

import io

import pytest

pytest.importorskip("reportlab")
pytest.importorskip("docling")

from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet  # noqa: E402
from reportlab.platypus import Paragraph, SimpleDocTemplate  # noqa: E402


def _pdf() -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()
    doc.build([
        Paragraph("Annual Report 2022 - Risk Factors", styles["Title"]),
        Paragraph("The independent auditor is Ernst and Young LLP.", styles["Normal"]),
    ])
    return buf.getvalue()


def test_docling_maps_to_parse_result() -> None:
    from provenance_services.docling_parser import parse_pdf_bytes_docling

    result = parse_pdf_bytes_docling(_pdf())
    assert "docling" in result.engine
    assert result.elements, "Docling should produce elements"
    blob = " ".join(e.text for e in result.elements).lower()
    assert "auditor" in blob or "risk factors" in blob
    for e in result.elements:  # contract: page + valid bbox + reading order (R60)
        assert e.page >= 0
        assert e.bbox.x1 >= e.bbox.x0 and e.bbox.y1 >= e.bbox.y0
    orders = [e.reading_order for e in result.elements]
    assert orders == sorted(orders)
