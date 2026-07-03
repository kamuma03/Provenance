"""Reranker for the Model service (R24).

Production uses a local cross-encoder (fastembed ONNX, e.g. ms-marco MiniLM). A lexical
(token-overlap) fallback keeps reranking working offline and in tests. Reranking runs
over the fused hybrid candidates in the retrieval core.
"""

from __future__ import annotations

import os
from typing import Protocol

from .embedder import _onnx_providers


class Reranker(Protocol):
    model_id: str

    def rerank(self, query: str, docs: list[str]) -> list[float]: ...


class LexicalReranker:
    """Token-overlap (Jaccard) scoring — deterministic, offline. Not semantic."""

    model_id = "lexical-fallback-v1"

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        q = set(query.lower().split())
        scores: list[float] = []
        for d in docs:
            dt = set(d.lower().split())
            scores.append(len(q & dt) / len(q | dt) if (q or dt) else 0.0)
        return scores


class CrossEncoderReranker:
    """Local ONNX cross-encoder via fastembed (lazy load; downloads on first use)."""

    def __init__(self, model_name: str) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        providers = _onnx_providers()
        self._model = TextCrossEncoder(model_name, providers=providers) if providers \
            else TextCrossEncoder(model_name)
        self.model_id = model_name

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        return [float(s) for s in self._model.rerank(query, docs)]


def get_reranker() -> Reranker:
    if os.environ.get("PROVENANCE_OFFLINE"):
        return LexicalReranker()
    model_name = os.environ.get("RERANKER_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")
    try:
        return CrossEncoderReranker(model_name)
    except Exception:  # pragma: no cover - offline => lexical fallback
        return LexicalReranker()
