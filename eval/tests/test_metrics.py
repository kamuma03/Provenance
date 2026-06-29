"""Eval metric unit tests (R42, R71)."""

from __future__ import annotations

from provenance_contracts import Answer, Claim
from provenance_eval.metrics import groundedness, numeric_exact_match, rate


def test_numeric_exact_match_normalizes_currency_and_commas() -> None:
    assert numeric_exact_match("$4.2 billion", Answer(text="revenue was 4.2 billion"))
    assert numeric_exact_match("1,234", Answer(text="the figure 1234 appears"))
    assert not numeric_exact_match("4.2 billion", Answer(text="revenue was 3.8 billion"))


def test_numeric_exact_match_false_on_refusal() -> None:
    assert not numeric_exact_match("4.2 billion", Answer(text="", refused=True))


def test_groundedness_counts_grounded_claims() -> None:
    a1 = Answer(text="x", claims=[Claim(text="a", grounded=True), Claim(text="b", grounded=True)])
    a2 = Answer(text="y", claims=[Claim(text="c", grounded=False)])
    assert groundedness([a1]) == 1.0
    assert groundedness([a1, a2]) == 2 / 3


def test_groundedness_is_one_when_nothing_released() -> None:
    assert groundedness([Answer(text="", refused=True)]) == 1.0


def test_rate() -> None:
    assert rate([True, True, False, True]) == 0.75
    assert rate([]) == 0.0
