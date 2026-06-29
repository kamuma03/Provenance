"""Parse engine tests (R60–R63) — digital-first path.

Generates a born-digital PDF (text + a gridded table) and asserts the parser emits typed
elements with page + bbox + reading order, keeps the table as one element, and records
the parse method as provenance.
"""

from __future__ import annotations

import io

import pytest
from provenance_contracts import ElementType, ParseMethod

reportlab = pytest.importorskip("reportlab")

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet  # noqa: E402
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle  # noqa: E402
from reportlab.platypus.paragraph import Paragraph  # noqa: E402


def _make_pdf() -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Annual Report 2022 — Risk Factors", styles["Title"]),
        Paragraph("The company faces market and operational risks.", styles["Normal"]),
        Table(
            [["Metric", "2022", "2021"], ["Revenue", "4.2B", "3.8B"]],
            style=TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]),
        ),
    ]
    doc.build(story)
    return buf.getvalue()


def test_digital_first_parse_yields_geometry_and_provenance() -> None:
    from provenance_services.parse_engine import parse_pdf_bytes

    result = parse_pdf_bytes(_make_pdf())

    assert result.pages == 1
    assert result.engine == "pdfplumber"
    assert result.parse_method is ParseMethod.TEXT_LAYER
    assert result.elements, "expected at least one element"

    # Every element carries page + a 4-tuple bbox (R6/R60).
    for el in result.elements:
        assert el.page == 0
        assert el.bbox.x1 >= el.bbox.x0 and el.bbox.y1 >= el.bbox.y0

    # Reading order is sequential 0..n-1 (R60).
    orders = [el.reading_order for el in result.elements]
    assert orders == list(range(len(result.elements)))

    # The text was captured.
    text_blob = " ".join(el.text for el in result.elements)
    assert "Risk Factors" in text_blob


def test_table_kept_as_coherent_unit() -> None:
    from provenance_services.parse_engine import parse_pdf_bytes

    result = parse_pdf_bytes(_make_pdf())
    tables = [el for el in result.elements if el.element_type is ElementType.TABLE]
    assert tables, "expected the gridded table to be detected as a TABLE element"
    # Cells stay together in one element (R62/R68).
    assert "Revenue" in tables[0].text and "4.2B" in tables[0].text
