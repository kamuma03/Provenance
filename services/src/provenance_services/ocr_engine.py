"""OCR fallback engine (R60–R64) — reads image-only pages, preserving bboxes.

Uses RapidOCR (ONNX PaddleOCR, Apache-2.0) — light, CPU, no torch, models bundled, and
crucially it returns geometry so citation highlight still works on scanned pages. Pages
are rendered with pypdfium2. (Docling + full PaddleOCR remain the richer Spark option.)
"""

from __future__ import annotations

import threading
from typing import Any

from provenance_contracts import BBox

OCR_ENGINE_ID = "rapidocr-onnxruntime"
RENDER_SCALE = 2.0  # render pages at 2x for legible OCR


class OcrEngine:
    def __init__(self) -> None:
        self._ocr = None  # lazy: model init is the costly part

    def _engine(self) -> Any:
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
        return self._ocr

    def ocr_pdf_page(self, content: bytes, page_index: int) -> list[tuple[str, BBox]]:
        """Render one PDF page to an image and OCR it → (text, bbox) in PDF coordinates."""
        import numpy as np
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(content)
        try:
            page = pdf[page_index]
            pw, ph = float(page.get_width()), float(page.get_height())  # PDF-point page size
            pil = page.render(scale=RENDER_SCALE).to_pil()
        finally:
            pdf.close()

        result, _ = self._engine()(np.array(pil))
        out: list[tuple[str, BBox]] = []
        for box, text, _conf in result or []:
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            bbox = BBox(
                page=page_index,
                x0=min(xs) / RENDER_SCALE, y0=min(ys) / RENDER_SCALE,
                x1=max(xs) / RENDER_SCALE, y1=max(ys) / RENDER_SCALE,
                page_width=pw, page_height=ph,  # carry page dims for citation scaling (L-10)
            )
            out.append((text, bbox))
        return out


_ENGINE: OcrEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_ocr() -> OcrEngine:
    # Parses run on a thread pool (H-5), so guard the lazy singleton against a construction
    # race that could build two RapidOCR sessions concurrently.
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = OcrEngine()
        return _ENGINE
