#!/usr/bin/env python3
"""License audit (R59) — fail the build on non-permissive dependencies.

Scans installed distributions and rejects copyleft (GPL/AGPL) and source-available
(SSPL/BSL/RSAL) licenses. Permissive licenses (Apache/MIT/BSD/PSF/MPL/ISC) pass.
An allowlist handles false positives (e.g. dual-licensed packages misreported by
classifier). Keeps the "fully open-source, on-prem-legal-clean" claim a tested property.
"""

from __future__ import annotations

import os
import sys
from importlib.metadata import distributions

# Substrings (lower-cased) that indicate a non-permissive license.
DENY = ("gpl", "agpl", "sspl", "business source", "bsl", "rsal", "commons clause")
# GPL substring also matches LGPL; treat LGPL as allowed (weak copyleft, dynamic-link OK).
ALLOW_SUBSTR = ("lgpl",)
# Package names explicitly cleared (false positives / reviewed exceptions).
ALLOWLIST: set[str] = set()

# Fail (not just warn) on distributions that declare no license at all. Off by default so
# the build stays green on the current tree; flip PROVENANCE_STRICT_LICENSE=1 in CI once the
# no-signal set has been reviewed and allowlisted (review H-12).
STRICT_NO_SIGNAL = os.environ.get("PROVENANCE_STRICT_LICENSE", "").lower() in ("1", "true", "yes")


def license_signal(classifiers: list[str], license_name: str, license_expression: str) -> str:
    """Combined license signal (lower-cased): SPDX classifiers + the License field name +
    the PEP 639 `License-Expression` (SPDX). The ecosystem is moving to License-Expression,
    so ignoring it left ~dozens of distributions invisible to the audit — a modern-packaged
    GPL dep could sail through (review H-12). The License *body* is still ignored to avoid
    false positives from permissive texts that quote other terms."""
    return " ".join([*classifiers, license_name, license_expression]).strip().lower()


def classify(signal: str) -> str:
    """'allow' | 'deny' | 'no-signal' for a combined license signal."""
    if not signal:
        return "no-signal"
    if any(a in signal for a in ALLOW_SUBSTR):
        return "allow"
    if any(d in signal for d in DENY):
        return "deny"
    return "allow"


def _license_text(dist) -> str:  # type: ignore[no-untyped-def]
    meta = dist.metadata
    classifiers = [v for k, v in meta.items() if k == "Classifier" and v.startswith("License")]
    license_field = (meta.get("License", "") or "").strip()
    name_line = license_field.splitlines()[0] if license_field else ""
    expression = (meta.get("License-Expression", "") or "").strip()
    return license_signal(classifiers, name_line, expression)


def main() -> int:
    violations: list[tuple[str, str]] = []
    no_signal: list[str] = []
    for dist in distributions():
        name = (dist.metadata.get("Name") or "?").lower()
        if name in ALLOWLIST:
            continue
        verdict = classify(_license_text(dist))
        if verdict == "deny":
            violations.append((name, _license_text(dist)[:80]))
        elif verdict == "no-signal":
            no_signal.append(name)

    if no_signal:
        label = "FAILED" if STRICT_NO_SIGNAL else "WARNING"
        print(f"License audit {label} — distributions with no license metadata (R59):")
        for name in sorted(set(no_signal)):
            print(f"  - {name}: (no Classifier / License / License-Expression)")

    if violations:
        print("LICENSE AUDIT FAILED — non-permissive dependencies detected (R59):")
        for name, lic in sorted(set(violations)):
            print(f"  - {name}: {lic}")
        return 1
    if no_signal and STRICT_NO_SIGNAL:
        return 1
    print("License audit passed: no copyleft / source-available dependencies.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
