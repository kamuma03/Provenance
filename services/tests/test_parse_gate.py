"""Per-document parse gate tests (R60–R62) — needs_deep_parse + auto routing."""

from __future__ import annotations

import io

import pytest

pytest.importorskip("reportlab")

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet  # noqa: E402
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle  # noqa: E402


def _prose_pdf() -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    s = getSampleStyleSheet()
    doc.build([Paragraph("Plain prose with no tables and a normal text layer.", s["Normal"])])
    return buf.getvalue()


def _table_pdf() -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    doc.build([
        Table([["Metric", "2022"], ["Revenue", "4.2B"]],
              style=TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)])),
    ])
    return buf.getvalue()


def test_probe_routes_prose_to_light_path() -> None:
    from provenance_services.parse_engine import needs_deep_parse

    assert needs_deep_parse(_prose_pdf()) is False  # clean prose → pdfplumber


def test_probe_routes_table_to_deep_path() -> None:
    from provenance_services.parse_engine import needs_deep_parse

    assert needs_deep_parse(_table_pdf()) is True  # table-bearing → Docling


def test_auto_uses_light_path_for_prose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARSE_ENGINE", "auto")
    from provenance_services.parse import parse_document

    result = parse_document(_prose_pdf())
    assert result.engine == "pdfplumber"  # gate chose the fast path, no Docling
    assert "prose" in " ".join(e.text for e in result.elements).lower()
