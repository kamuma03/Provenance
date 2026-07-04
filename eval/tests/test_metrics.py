"""Eval metric unit tests (R42, R71)."""

from __future__ import annotations

from provenance_contracts import Answer
from provenance_eval.metrics import groundedness, numeric_exact_match, rate

_CORPUS = (
    "Total revenue for fiscal 2022 was 4.2 billion dollars. "
    "The independent auditor of the company is Ernst and Young LLP."
)


def test_numeric_exact_match_normalizes_currency_and_commas() -> None:
    assert numeric_exact_match("$4.2 billion", Answer(text="revenue was 4.2 billion"))
    assert numeric_exact_match("1,234", Answer(text="the figure 1234 appears"))
    assert not numeric_exact_match("4.2 billion", Answer(text="revenue was 3.8 billion"))


def test_numeric_exact_match_false_on_refusal() -> None:
    assert not numeric_exact_match("4.2 billion", Answer(text="", refused=True))


def test_numeric_exact_match_is_boundary_aware_not_substring() -> None:
    # The order-of-magnitude hallucination R42 exists to catch: "14.2 billion" must NOT
    # satisfy an expected "4.2 billion" (review M-2).
    assert not numeric_exact_match("4.2 billion", Answer(text="revenue was 14.2 billion"))
    assert numeric_exact_match("4.2 billion", Answer(text="revenue was 4.2 billion last year"))
    # trailing punctuation on the matched token must not defeat the match
    assert numeric_exact_match("4.2 billion", Answer(text="Revenue was 4.2 billion."))


def test_groundedness_scores_released_text_against_corpus() -> None:
    # Faithful answer: every salient token comes from the corpus ⇒ fully grounded.
    faithful = Answer(text="Total revenue for fiscal 2022 was 4.2 billion dollars.")
    assert groundedness([faithful], _CORPUS) == 1.0


def test_groundedness_catches_hallucination_independent_of_self_report() -> None:
    # A fabricated answer is caught even though nothing in the Answer marks it ungrounded —
    # the metric no longer trusts the system's own report (review C-2).
    hallucination = Answer(text="The company was founded on Mars in 1842.")
    assert groundedness([hallucination], _CORPUS) < 0.85  # below the §9.2 fail threshold


def test_groundedness_is_one_when_nothing_released() -> None:
    assert groundedness([Answer(text="", refused=True)], _CORPUS) == 1.0


def test_rate() -> None:
    assert rate([True, True, False, True]) == 0.75
    assert rate([]) == 0.0
