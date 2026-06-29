"""Smoke eval — retrieval recall (R45).

The P2 smoke gate measures whether retrieval surfaces the relevant chunk for each query
(recall@k) — an LLM-free check that retrieval works. Full RAGAS faithfulness (LLM-judged)
lands as the P4 CI gate (§9.2).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

# Retrieval function: (query, k) -> list of retrieved chunk ids, best-first.
RetrieveFn = Callable[[str, int], Awaitable[list[str]]]

# A case: (query, set of acceptable gold chunk ids).
Case = tuple[str, set[str]]

SMOKE_RECALL_THRESHOLD = 0.8


async def retrieval_recall(retrieve_fn: RetrieveFn, cases: list[Case], k: int = 5) -> float:
    """Fraction of cases where a gold chunk appears in the top-k retrieved set."""
    if not cases:
        return 0.0
    hits = 0
    for query, gold in cases:
        retrieved = set(await retrieve_fn(query, k))
        if gold & retrieved:
            hits += 1
    return hits / len(cases)
