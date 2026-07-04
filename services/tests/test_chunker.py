"""Structure-aware chunker tests (R68)."""

from __future__ import annotations

from provenance_contracts import BBox, ElementType, ParsedElement
from provenance_services.chunker import chunk_elements


def _text(order: int, page: int, s: str) -> ParsedElement:
    return ParsedElement(
        element_type=ElementType.TEXT, text=s, page=page,
        bbox=BBox(page=page, x0=0, y0=order, x1=100, y1=order + 10), reading_order=order,
    )


def _table(order: int, page: int, s: str) -> ParsedElement:
    return ParsedElement(
        element_type=ElementType.TABLE, text=s, page=page,
        bbox=BBox(page=page, x0=0, y0=order, x1=100, y1=order + 50), reading_order=order,
    )


def test_table_becomes_its_own_chunk() -> None:
    els = [
        _text(0, 0, "intro line"),
        _table(1, 0, "Metric | 2022\nRevenue | 4.2B"),
        _text(2, 0, "after"),
    ]
    chunks = chunk_elements(els, document_id="d1", kb_id="kb1")
    tables = [c for c in chunks if c.element_type is ElementType.TABLE]
    assert len(tables) == 1
    assert "Revenue | 4.2B" in tables[0].text  # kept intact (R68)
    # Prose around the table is not merged into the table chunk.
    assert all("intro line" not in t.text for t in tables)


def test_prose_packs_to_target_size_with_chunk_ids() -> None:
    els = [_text(i, 0, "x" * 300) for i in range(5)]  # 1500 chars total
    chunks = chunk_elements(els, document_id="d1", kb_id="kb1", target_chars=600, overlap_chars=0)
    assert len(chunks) >= 2  # packed into multiple chunks
    assert [c.id for c in chunks] == [f"d1:c{i}" for i in range(len(chunks))]
    for c in chunks:
        assert c.page == 0
        assert c.bbox.x1 >= c.bbox.x0 and c.bbox.y1 >= c.bbox.y0


def test_page_boundary_splits_chunks() -> None:
    els = [_text(0, 0, "page one"), _text(1, 1, "page two")]
    chunks = chunk_elements(els, document_id="d1", kb_id="kb1", target_chars=10_000)
    pages = {c.page for c in chunks}
    assert pages == {0, 1}  # never merged across pages


def test_overlap_carry_does_not_emit_duplicate_tail_at_boundaries() -> None:
    # With overlap enabled, a size-flush keeps a small last element as an overlap tail. At the
    # following page boundary that carried tail must NOT be re-emitted as its own chunk — that
    # duplicated the tail already present in the previous chunk (review M-9).
    els = [
        _text(0, 0, "x" * 96),                # nearly fills the 100-char target
        _text(1, 0, "tail"),                  # tips over target; small enough to be carried
        _text(2, 1, "charlie on page two"),   # page boundary forces a flush of the carried tail
    ]
    chunks = chunk_elements(
        els, document_id="d1", kb_id="kb1", target_chars=100, overlap_chars=50
    )
    # The first chunk already contains "tail"; no later chunk may consist solely of it.
    assert "tail" in chunks[0].text
    assert all(c.text != "tail" for c in chunks[1:])  # the carried tail is not duplicated
    assert [c.id for c in chunks] == [f"d1:c{i}" for i in range(len(chunks))]  # contiguous ids
    assert any("charlie on page two" in c.text for c in chunks)  # page-two content survives
