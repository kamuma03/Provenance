"""Reranker tests (R24) — lexical fallback (deterministic, offline)."""

from __future__ import annotations

from provenance_services.reranker import LexicalReranker


def test_lexical_reranker_scores_overlap() -> None:
    rr = LexicalReranker()
    query = "supply chain disruption"
    docs = [
        "board meeting notes",                 # no overlap
        "supply chain disruption risk factor",  # high overlap
        "quarterly supply update",              # partial overlap
    ]
    scores = rr.rerank(query, docs)
    # The most lexically-overlapping doc scores highest.
    assert scores.index(max(scores)) == 1
    assert scores[0] == 0.0  # no shared tokens


def test_empty_query_is_safe() -> None:
    rr = LexicalReranker()
    assert rr.rerank("", ["anything"]) == [0.0]
