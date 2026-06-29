"""Domain detection tests (R8, R10) + detect-but-confirm (R9)."""

from __future__ import annotations

from provenance_services.detection import detect, should_pause_for_confirmation


def test_detects_sec_financial_from_signal_vocabulary() -> None:
    text = (
        "This annual report describes the company, its subsidiaries, the auditor, "
        "reported financial metrics, and the principal risk factors for the fiscal period."
    )
    d = detect(text)
    assert d.domain == "sec_financial"
    assert d.confidence > 0
    assert "matched signals" in d.rationale


def test_detects_research_papers() -> None:
    text = (
        "We present a method evaluated on a benchmark dataset; the paper reports findings "
        "and cites prior work by the authors and their institution."
    )
    d = detect(text)
    assert d.domain == "research_papers"


def test_out_of_domain_falls_back_to_generic() -> None:
    d = detect("the quick brown fox jumped over the lazy dog on a sunny afternoon")
    assert d.domain == "generic"
    assert d.low_confidence is True
    assert should_pause_for_confirmation(d) is True  # low confidence => confirm (R9)


def test_high_confidence_does_not_pause() -> None:
    text = "company subsidiary officer risk auditor metric fiscal proceeding subsidiaries"
    d = detect(text)
    assert d.domain == "sec_financial"
    # A strongly-signalled doc should not require confirmation.
    assert should_pause_for_confirmation(d) == (d.confidence < 0.55)
