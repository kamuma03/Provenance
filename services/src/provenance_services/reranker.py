"""Reranker for the Model service (R24).

Production uses a local ONNX cross-encoder. fastembed ships several (ms-marco MiniLM,
bge-reranker-base); a model it doesn't ship — BAAI/bge-reranker-v2-m3 (R66 default) — is
exported to ONNX at image build and loaded from a baked directory here. Both run on the
GPU (CUDAExecutionProvider) when PROVENANCE_ONNX_CUDA is set. A lexical (token-overlap)
fallback keeps reranking working offline and in tests. Reranking runs over the fused
hybrid candidates in the retrieval core.
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


class OnnxCrossEncoderReranker:
    """Cross-encoder over a build-time ONNX export (a model fastembed doesn't ship, e.g.
    BAAI/bge-reranker-v2-m3). Runs on CUDAExecutionProvider when PROVENANCE_ONNX_CUDA is
    set. Tokenizes with the exported tokenizer.json via the `tokenizers` lib, so there is no
    transformers/optimum dependency at runtime — only onnxruntime + tokenizers (both present).
    """

    def __init__(self, model_dir: str, model_id: str) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.model_id = model_id
        self._tokenizer = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        providers = _onnx_providers() or ["CPUExecutionProvider"]
        self._session = ort.InferenceSession(
            os.path.join(model_dir, "model.onnx"), providers=providers
        )
        self._input_names = {i.name for i in self._session.get_inputs()}

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        import numpy as np

        if not docs:
            return []
        # (query, doc) pairs; tokenizer.json's post-processor builds the cross-encoder template.
        encodings = self._tokenizer.encode_batch([(query, doc) for doc in docs])
        length = max(len(enc.ids) for enc in encodings)
        input_ids = np.zeros((len(encodings), length), dtype=np.int64)
        attention = np.zeros((len(encodings), length), dtype=np.int64)
        for row, enc in enumerate(encodings):
            input_ids[row, : len(enc.ids)] = enc.ids
            attention[row, : len(enc.attention_mask)] = enc.attention_mask
        feeds = {
            name: value
            for name, value in (("input_ids", input_ids), ("attention_mask", attention))
            if name in self._input_names
        }
        logits = self._session.run(None, feeds)[0]
        return [float(x) for x in np.asarray(logits).reshape(-1)]


def _baked_onnx_dir(model_id: str) -> str | None:
    """Directory of a build-time ONNX export for model_id, if one is baked into the image.
    RERANKER_ONNX_DIR overrides; otherwise <RERANKER_ONNX_ROOT>/<model basename> — where the
    Dockerfile writes the export (R66). Returns None when there's no local export."""
    explicit = os.environ.get("RERANKER_ONNX_DIR")
    root = os.environ.get("RERANKER_ONNX_ROOT", "/opt/models")
    candidate = explicit or os.path.join(root, model_id.rsplit("/", 1)[-1])
    return candidate if os.path.exists(os.path.join(candidate, "model.onnx")) else None


def get_reranker() -> Reranker:
    if os.environ.get("PROVENANCE_OFFLINE"):
        return LexicalReranker()
    model_name = os.environ.get("RERANKER_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")
    baked = _baked_onnx_dir(model_name)
    if baked is not None:  # a model we exported ourselves (e.g. bge-reranker-v2-m3)
        try:
            return OnnxCrossEncoderReranker(baked, model_name)
        except Exception:  # pragma: no cover - fall through to fastembed / lexical
            pass
    try:
        return CrossEncoderReranker(model_name)
    except Exception:  # pragma: no cover - offline => lexical fallback
        return LexicalReranker()
