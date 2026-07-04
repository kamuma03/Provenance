"""Embedder selection tests (R66) — fail-fast vs. deliberate offline fallback (H-7)."""

from __future__ import annotations

import pytest
from provenance_services import embedder as emb


def test_offline_uses_deterministic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVENANCE_OFFLINE", "1")
    assert isinstance(emb.get_embedder(), emb.DeterministicEmbedder)


def test_online_load_failure_fails_fast_not_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    # A model-load failure outside offline mode must raise, never silently serve hash
    # pseudo-embeddings that would ground answers in noise (review H-7).
    monkeypatch.delenv("PROVENANCE_OFFLINE", raising=False)

    def boom(_model_name: str) -> emb.Embedder:
        raise RuntimeError("model download failed")

    monkeypatch.setattr(emb, "FastEmbedEmbedder", boom)
    with pytest.raises(RuntimeError, match="refusing to serve hash"):
        emb.get_embedder()
