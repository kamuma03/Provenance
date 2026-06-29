"""Eval CI gate (R44) — run the system over the eval set, score, fail below thresholds.

Computes the offline-gateable metrics (numeric exact-span, detection accuracy, honest-
refusal, answer-rate/over-refusal, retrieval recall, groundedness) and exits non-zero if
any is below its §9.2 fail threshold. LLM-judged RAGAS metrics run on the Spark.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import yaml
from provenance_services.detection import detect

from .harness import EvalCase, InProcessSystem, Outcome, run_cases
from .metrics import THRESHOLDS, groundedness, numeric_exact_match, rate

DEFAULT_EVAL_SET = Path(__file__).resolve().parents[3] / "eval" / "golden" / "eval_set.yaml"


async def _build_outcomes(spec: dict) -> tuple[list[Outcome], dict]:
    system = InProcessSystem(str(Path(tempfile.mkdtemp(prefix="prov-eval-")) / "kuzu"))
    try:
        for doc in spec.get("corpus", []):
            await system.ingest(doc["kb"], doc["doc_id"], doc["text"])
        cases = [EvalCase(**c) for c in spec.get("cases", [])]
        outcomes = await run_cases(system, cases)
    finally:
        system.close()
    return outcomes, spec


def compute_metrics(outcomes: list[Outcome], detection: list[dict]) -> dict[str, float]:
    answers = [o.answer for o in outcomes]
    numeric = [o for o in outcomes if o.case.cohort == "numeric_factual"]
    answerable = [o for o in outcomes if o.case.answerable]
    ooc = [o for o in outcomes if o.case.cohort == "out_of_corpus"]
    recall_cases = [o for o in answerable if o.case.gold_contains]

    numeric_flags = [numeric_exact_match(o.case.expected, o.answer) for o in numeric]
    return {
        "numeric_exactness": rate(numeric_flags),
        "honest_refusal_rate": rate([o.answer.refused for o in ooc]),
        "answer_rate": rate([not o.answer.refused for o in answerable]),
        "retrieval_recall": rate([
            any(o.case.gold_contains.lower() in t.lower() for t in o.retrieved_texts)
            for o in recall_cases
        ]),
        "groundedness": groundedness(answers),
        "detection_accuracy": rate([detect(d["text"]).domain == d["expected"] for d in detection]),
    }


def evaluate(spec: dict) -> tuple[dict[str, float], list[str]]:
    outcomes, _ = asyncio.run(_build_outcomes(spec))
    metrics = compute_metrics(outcomes, spec.get("detection", []))
    failures = [
        f"{name}={value:.3f} < fail_below={THRESHOLDS[name].fail_below}"
        for name, value in metrics.items()
        if name in THRESHOLDS and value < THRESHOLDS[name].fail_below
    ]
    return metrics, failures


def main(path: Path = DEFAULT_EVAL_SET) -> int:
    spec = yaml.safe_load(path.read_text())
    metrics, failures = evaluate(spec)

    print("=== Provenance eval gate (offline-computable metrics) ===")
    for name, value in sorted(metrics.items()):
        th = THRESHOLDS[name]
        ok = "PASS" if value >= th.fail_below else "FAIL"
        print(f"  [{ok}] {name:20s} {value:.3f}  (target {th.target}, fail<{th.fail_below})")
    print("  [skip] RAGAS faithfulness/relevancy/precision/recall — LLM-judged on the Spark")

    if failures:
        print("\nGATE FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nGATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
