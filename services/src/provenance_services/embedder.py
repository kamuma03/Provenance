"""Embedding models for the Model service (R66).

Production uses a local fastembed model (BGE/E5, ONNX — air-gap-friendly, Apache-2.0),
loaded lazily on the GPU box. A deterministic fallback provides stable offline vectors so
the system (and tests) run without a model download. The model id is exposed so the Vector
service can record it per index and reject mismatched query embeddings (R66).
"""

from __future__ import annotations

import hashlib
import os
import struct
from typing import Protocol


class Embedder(Protocol):
    model_id: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class DeterministicEmbedder:
    """Hash-based pseudo-embeddings: stable, offline, dim-correct. Not semantic."""

    model_id = "deterministic-fallback-v1"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        out: list[float] = []
        counter = 0
        while len(out) < self.dim:
            digest = hashlib.sha256(f"{text}:{counter}".encode()).digest()
            for j in range(0, len(digest), 4):
                if len(out) >= self.dim:
                    break
                out.append(struct.unpack("<I", digest[j : j + 4])[0] / 2**32 - 0.5)
            counter += 1
        return out

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class FastEmbedEmbedder:
    """Local ONNX embedding via fastembed (lazy model load; downloads on first use)."""

    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name)
        self.model_id = model_name
        self.dim = len(next(iter(self._model.embed(["probe"]))))

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(texts)]


def get_embedder() -> Embedder:
    """Real fastembed model if available; otherwise the deterministic fallback."""
    model_name = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    try:
        return FastEmbedEmbedder(model_name)
    except Exception:  # pragma: no cover - offline / no model => deterministic
        return DeterministicEmbedder()
