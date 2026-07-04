"""License-audit classifier tests (R59, review H-12) — PEP 639 License-Expression."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_AUDIT = Path(__file__).resolve().parents[2] / "scripts" / "license_audit.py"
_spec = importlib.util.spec_from_file_location("license_audit", _AUDIT)
assert _spec and _spec.loader
license_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(license_audit)


def test_permissive_classifier_allows() -> None:
    sig = license_audit.license_signal(
        ["License :: OSI Approved :: Apache Software License"], "Apache-2.0", ""
    )
    assert license_audit.classify(sig) == "allow"


def test_gpl_via_pep639_license_expression_is_denied() -> None:
    # A modern package that declares its license ONLY via License-Expression must not slip
    # through the audit — this was the H-12 blind spot.
    sig = license_audit.license_signal([], "", "GPL-3.0-only")
    assert license_audit.classify(sig) == "deny"


def test_lgpl_expression_is_allowed_as_weak_copyleft() -> None:
    sig = license_audit.license_signal([], "", "LGPL-3.0-or-later")
    assert license_audit.classify(sig) == "allow"


def test_no_license_metadata_is_flagged_not_silently_passed() -> None:
    assert license_audit.classify(license_audit.license_signal([], "", "")) == "no-signal"
