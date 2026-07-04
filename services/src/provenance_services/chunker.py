"""Structure-aware chunker (R68).

Consumes Parse elements and produces retrievable Chunks: prose is packed to a target
size with overlap; tables are kept as coherent units (one chunk each, never split
mid-row). Each chunk carries page + a bbox (union of its source elements) + reading order.
"""

from __future__ import annotations

from provenance_contracts import BBox, Chunk, ElementType, ParsedElement

TARGET_CHARS = 1000
OVERLAP_CHARS = 150


def _union_bbox(elements: list[ParsedElement]) -> BBox:
    page = elements[0].page
    return BBox(
        page=page,
        x0=min(e.bbox.x0 for e in elements),
        y0=min(e.bbox.y0 for e in elements),
        x1=max(e.bbox.x1 for e in elements),
        y1=max(e.bbox.y1 for e in elements),
    )


def chunk_elements(
    elements: list[ParsedElement],
    *,
    document_id: str,
    kb_id: str,
    target_chars: int = TARGET_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
) -> list[Chunk]:
    """Group Parse elements into Chunks. Tables stay whole (R68)."""
    chunks: list[Chunk] = []
    buffer: list[ParsedElement] = []  # accumulating prose elements (same page)
    carried_only = False  # buffer currently holds ONLY an overlap tail carried from last flush

    def flush(carry_overlap: bool = False) -> None:
        nonlocal carried_only
        if not buffer:
            return
        # A buffer that is nothing but the carried-over overlap tail (no new content appended
        # since) would duplicate the previous chunk's tail as its own chunk — a real problem at
        # page/document boundaries. Drop it instead of emitting a duplicate (review M-9).
        if carried_only and not carry_overlap:
            buffer.clear()
            carried_only = False
            return
        text = "\n".join(e.text for e in buffer)
        bbox = _union_bbox(buffer)
        idx = len(chunks)
        chunks.append(
            Chunk(
                id=f"{document_id}:c{idx}",
                document_id=document_id,
                kb_id=kb_id,
                text=text,
                page=bbox.page,
                bbox=bbox,
                reading_order=idx,
                element_type=ElementType.TEXT,
            )
        )
        # Carry an overlap tail into the next chunk for prose continuity — but only on
        # a size-based flush (never across a page boundary, which would mix pages).
        tail = buffer[-1]
        keep_tail = carry_overlap and overlap_chars > 0 and len(tail.text) <= overlap_chars
        buffer[:] = [tail] if keep_tail else []
        carried_only = keep_tail

    for el in sorted(elements, key=lambda e: e.reading_order):
        if el.element_type is ElementType.TABLE:
            flush()  # close any open prose chunk
            idx = len(chunks)
            chunks.append(
                Chunk(
                    id=f"{document_id}:c{idx}",
                    document_id=document_id,
                    kb_id=kb_id,
                    text=el.text,
                    page=el.page,
                    bbox=el.bbox,
                    reading_order=idx,
                    element_type=ElementType.TABLE,
                )
            )
            continue

        # Page boundary closes the current chunk (don't merge across pages).
        if buffer and el.page != buffer[-1].page:
            flush()
        buffer.append(el)
        carried_only = False  # real new content in the buffer now
        if sum(len(e.text) for e in buffer) >= target_chars:
            flush(carry_overlap=True)

    flush()
    return chunks
