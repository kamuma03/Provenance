"""Docling parsing backend (R60–R64) — the richer document-understanding pipeline.

Docling does layout analysis + table structure (TableFormer) + reading order and uses
PaddleOCR (via RapidOCR ONNX) for raster pages, then we map its output onto our
ParseResult contract (typed elements with page + bbox + reading order). Heavier than the
pdfplumber+RapidOCR backend (pulls torch); selected via PARSE_ENGINE=docling.
"""

from __future__ import annotations

import io

from provenance_contracts import BBox, ElementType, ParsedElement, ParseMethod, ParseResult

DOCLING_ENGINE = "docling+paddleocr"

_HEADINGS = {"section_header", "title", "page_header"}


def _bbox(prov_item, page_index: int) -> BBox:  # type: ignore[no-untyped-def]
    bb = prov_item.bbox
    xs = [float(bb.l), float(bb.r)]
    ys = [float(bb.t), float(bb.b)]
    return BBox(page=page_index, x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys))


def parse_pdf_bytes_docling(content: bytes) -> ParseResult:
    from docling.datamodel.base_models import DocumentStream
    from docling.document_converter import DocumentConverter
    from docling_core.types.doc import TableItem, TextItem

    source = DocumentStream(name="document.pdf", stream=io.BytesIO(content))
    doc = DocumentConverter().convert(source).document

    elements: list[ParsedElement] = []
    order = 0
    for item, _level in doc.iterate_items():
        if not getattr(item, "prov", None):
            continue
        prov = item.prov[0]
        page_index = int(prov.page_no) - 1  # Docling pages are 1-indexed; we use 0-indexed

        if isinstance(item, TableItem):
            text = item.export_to_markdown(doc=doc) if hasattr(item, "export_to_markdown") else ""
            etype = ElementType.TABLE
        elif isinstance(item, TextItem):
            text = item.text
            label = str(getattr(item, "label", "text"))
            etype = ElementType.HEADING if label in _HEADINGS else ElementType.TEXT
        else:
            continue
        if not text.strip():
            continue

        elements.append(
            ParsedElement(
                element_type=etype, text=text, page=page_index,
                bbox=_bbox(prov, page_index), reading_order=order,
            )
        )
        order += 1

    n_pages = doc.num_pages() if hasattr(doc, "num_pages") else 1
    return ParseResult(
        elements=elements,
        pages=n_pages or 1,
        parse_method=ParseMethod.TEXT_LAYER,  # Docling handles text-layer vs OCR internally
        page_methods={},
        engine=DOCLING_ENGINE,
        engine_version="docling",
    )
