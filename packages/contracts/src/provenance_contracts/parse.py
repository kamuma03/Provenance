"""Parse service response contract (R60).

The typed elements the Parse service returns and the chunker consumes. Lives in
contracts because it is the Parse → Ingestion API boundary (single source of truth, N9).
"""

from __future__ import annotations

from pydantic import BaseModel

from .domain import BBox, ElementType, ParseMethod


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
