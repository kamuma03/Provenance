"""OCR fallback engine (R60–R64) — reads image-only pages, preserving bboxes.

Uses RapidOCR (ONNX PaddleOCR, Apache-2.0) — light, CPU, no torch, models bundled, and
crucially it returns geometry so citation highlight still works on scanned pages. Pages
are rendered with pypdfium2. (Docling + full PaddleOCR remain the richer Spark option.)
"""

from __future__ import annotations

import os
import threading
from typing import Any

from provenance_contracts import BBox

OCR_ENGINE_ID = "rapidocr-onnxruntime"
# Render pages at 1.5x — legible for OCR while keeping bitmaps (and thus the onnxruntime
# arena's peak, which it never returns to the OS) ~44% smaller than 2x. Override via env.
RENDER_SCALE = float(os.environ.get("OCR_RENDER_SCALE", "1.5"))


class OcrEngine:
    def __init__(self) -> None:
        self._ocr = None  # lazy: model init is the costly part

    def _engine(self) -> Any:
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            # Disable onnxruntime's CPU BFC arena: it grows to the largest tensor it has seen
            # and never releases it, so varying page sizes ratchet RSS up over a long run.
            # Off = allocate per-inference (a little slower, but no unbounded working set).
            try:
                self._ocr = RapidOCR(
                    det_use_cuda=False, cls_use_cuda=False, rec_use_cuda=False,
                    intra_op_num_threads=int(os.environ.get("OMP_NUM_THREADS", "4")),
                    enable_cpu_mem_arena=False,
                )
            except Exception:  # noqa: BLE001 - RapidOCR API varies by version; never fail init
                # Older RapidOCR without these kwargs — fall back to defaults.
                self._ocr = RapidOCR()
        return self._ocr

    def ocr_pdf_pages(
        self, content: bytes, page_indices: list[int]
    ) -> dict[int, list[tuple[str, BBox]]]:
        """OCR several pages of one PDF, opening the document ONCE. Returns
        ``{page_index: [(text, bbox), ...]}`` in PDF coordinates.

        Opening once (vs once per page) avoids re-parsing a multi-MB PDF dozens of times,
        which churned pypdfium2's native heap; render buffers are freed promptly to keep the
        onnxruntime arena's peak — and thus RSS — small over a long run (memory-growth fix)."""
        import numpy as np
        import pypdfium2 as pdfium

        engine = self._engine()
        results: dict[int, list[tuple[str, BBox]]] = {}
        pdf = pdfium.PdfDocument(content)
        try:
            for page_index in page_indices:
                page = pdf[page_index]
                pw, ph = float(page.get_width()), float(page.get_height())
                arr = np.asarray(page.render(scale=RENDER_SCALE).to_pil())
                result, _ = engine(arr)
                del arr  # free the render buffer before the next page
                out: list[tuple[str, BBox]] = []
                for box, text, _conf in result or []:
                    xs = [float(p[0]) for p in box]
                    ys = [float(p[1]) for p in box]
                    out.append((text, BBox(
                        page=page_index,
                        x0=min(xs) / RENDER_SCALE, y0=min(ys) / RENDER_SCALE,
                        x1=max(xs) / RENDER_SCALE, y1=max(ys) / RENDER_SCALE,
                        page_width=pw, page_height=ph,  # dims for citation scaling (L-10)
                    )))
                results[page_index] = out
        finally:
            pdf.close()
        return results

    def ocr_pdf_page(self, content: bytes, page_index: int) -> list[tuple[str, BBox]]:
        """Single-page convenience wrapper over ocr_pdf_pages (kept for callers/tests)."""
        return self.ocr_pdf_pages(content, [page_index]).get(page_index, [])


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
