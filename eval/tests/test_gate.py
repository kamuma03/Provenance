"""Eval gate tests (R44) — the gate passes on the eval set, and fails on regression."""

from __future__ import annotations

import yaml
from provenance_contracts import Answer
from provenance_eval.gate import DEFAULT_EVAL_SET, compute_metrics, evaluate
from provenance_eval.harness import EvalCase, Outcome
from provenance_eval.metrics import THRESHOLDS


def test_gate_passes_on_eval_set() -> None:
    """Runs the real in-process system over the eval set; all offline metrics pass."""
    spec = yaml.safe_load(DEFAULT_EVAL_SET.read_text())
    metrics, failures = evaluate(spec)
    assert failures == [], f"gate should pass but failed: {failures}"
    assert metrics["numeric_exactness"] == 1.0
    assert metrics["detection_accuracy"] >= THRESHOLDS["detection_accuracy"].fail_below


def test_gate_detects_under_refusal_regression() -> None:
    """If the system answers an out-of-corpus query, the gate must catch it (R71)."""
    leaked = Outcome(
        case=EvalCase(id="o", cohort="out_of_corpus", kb="k", query="q", answerable=False),
        answer=Answer(text="a fabricated answer", claims=[]),  # NOT refused
    )
    metrics = compute_metrics([leaked], detection=[])
    assert metrics["honest_refusal_rate"] == 0.0
    failures = [
        n for n, v in metrics.items()
        if n in THRESHOLDS and v < THRESHOLDS[n].fail_below
    ]
    assert "honest_refusal_rate" in failures


def test_gate_detects_numeric_regression() -> None:
    wrong = Outcome(
        case=EvalCase(id="n", cohort="numeric_factual", kb="k", query="revenue",
                      expected="4.2 billion", answerable=True, gold_contains="revenue"),
        answer=Answer(text="revenue was 9.9 billion", claims=[]),
    )
    metrics = compute_metrics([wrong], detection=[])
    assert metrics["numeric_exactness"] < THRESHOLDS["numeric_exactness"].fail_below
