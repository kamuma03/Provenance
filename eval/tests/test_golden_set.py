"""Golden-set seed validation (R40)."""

from __future__ import annotations

from provenance_eval.golden import DEFAULT_PATH, Cohort, load_golden


def test_golden_set_loads_and_is_well_formed() -> None:
    gs = load_golden(DEFAULT_PATH)
    assert len(gs.items) >= 5  # P1 seed

    cohorts = {i.cohort for i in gs.items}
    # The seed spans the cohorts the P4 gate scores (§9.2).
    for required in (
        Cohort.TEXTUAL_FACTUAL,
        Cohort.NUMERIC_FACTUAL,
        Cohort.RELATIONAL,
        Cohort.OUT_OF_CORPUS,
        Cohort.ANSWERABLE,
    ):
        assert required in cohorts, f"missing cohort {required}"


def test_answerable_items_carry_a_source_span() -> None:
    gs = load_golden(DEFAULT_PATH)
    for item in gs.items:
        if item.answerable and item.cohort is not Cohort.DOMAIN_DETECTION:
            assert item.source is not None, f"{item.id} answerable but has no source span"


def test_out_of_corpus_items_are_unanswerable() -> None:
    gs = load_golden(DEFAULT_PATH)
    ooc = gs.by_cohort(Cohort.OUT_OF_CORPUS)
    assert ooc and all(i.answerable is False for i in ooc)  # honest-refusal cohort (§9.2)


def test_detection_item_expected_is_a_known_domain() -> None:
    from provenance_contracts import REGISTRY

    gs = load_golden(DEFAULT_PATH)
    for item in gs.by_cohort(Cohort.DOMAIN_DETECTION):
        assert item.expected in REGISTRY
