"""Parse engine — layout-aware document parsing (R60–R64).

Digital-first (R61): born-digital PDFs are parsed from their text layer with pdfplumber
(fast, no models) — yielding typed elements with page + bbox + reading order, and tables
kept as coherent units (R62, R68). Image-only pages fall back to OCR via the configured
engine (Docling + PaddleOCR), which is loaded lazily and runs on the DGX Spark.
"""

from __future__ import annotations

import io

import pdfplumber
from provenance_contracts import BBox, ElementType, ParseMethod
from pydantic import BaseModel

DIGITAL_ENGINE = "pdfplumber"
DIGITAL_ENGINE_VERSION = pdfplumber.__version__


class ParsedElement(BaseModel):
    element_type: ElementType
    text: str
    page: int
    bbox: BBox
    reading_order: int


class ParseResult(BaseModel):
    elements: list[ParsedElement]
    pages: int
    parse_method: ParseMethod  # dominant method across pages (R63)
    page_methods: dict[int, ParseMethod]
    engine: str
    engine_version: str


def _center_in(bbox: tuple[float, float, float, float], top: float, bottom: float) -> bool:
    """Is a line's vertical center inside a table's vertical span?"""
    cy = (top + bottom) / 2
    return bbox[1] <= cy <= bbox[3]


def parse_pdf_bytes(content: bytes) -> ParseResult:
    """Digital-first parse of a PDF. Pages without a text layer are flagged for OCR."""
    elements: list[ParsedElement] = []
    page_methods: dict[int, ParseMethod] = {}
    raw: list[tuple[int, float, float, ElementType, str, BBox]] = []

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        n_pages = len(pdf.pages)
        for pidx, page in enumerate(pdf.pages):
            tables = page.find_tables()
            table_spans = [t.bbox for t in tables]

            # Tables first — kept as coherent units (R62/R68).
            for t in tables:
                rows = t.extract()
                text = "\n".join(
                    " | ".join((c or "").strip() for c in row) for row in rows if row
                )
                x0, top, x1, bottom = t.bbox
                raw.append(
                    (pidx, top, x0, ElementType.TABLE, text,
                     BBox(page=pidx, x0=x0, y0=top, x1=x1, y1=bottom))
                )

            # Text lines outside any table bbox (avoid duplicating table text).
            lines = page.extract_text_lines() if hasattr(page, "extract_text_lines") else []
            for ln in lines:
                top, bottom = float(ln["top"]), float(ln["bottom"])
                if any(_center_in(span, top, bottom) for span in table_spans):
                    continue
                raw.append(
                    (pidx, top, float(ln["x0"]), ElementType.TEXT, ln["text"],
                     BBox(page=pidx, x0=float(ln["x0"]), y0=top,
                          x1=float(ln["x1"]), y1=bottom))
                )

            page_methods[pidx] = (
                ParseMethod.TEXT_LAYER if (lines or tables) else ParseMethod.OCR
            )

    # Reading order: sort by (page, top, x0) and number sequentially (R60).
    raw.sort(key=lambda r: (r[0], r[1], r[2]))
    for order, (page, _top, _x0, etype, text, bbox) in enumerate(raw):
        elements.append(
            ParsedElement(element_type=etype, text=text, page=page, bbox=bbox, reading_order=order)
        )

    ocr_pages = [p for p, m in page_methods.items() if m is ParseMethod.OCR]
    dominant = ParseMethod.OCR if (ocr_pages and not elements) else ParseMethod.TEXT_LAYER
    return ParseResult(
        elements=elements,
        pages=n_pages,
        parse_method=dominant,
        page_methods=page_methods,
        engine=DIGITAL_ENGINE,
        engine_version=DIGITAL_ENGINE_VERSION,
    )
