#!/usr/bin/env python3
"""License audit (R59) — fail the build on non-permissive dependencies.

Scans installed distributions and rejects copyleft (GPL/AGPL) and source-available
(SSPL/BSL/RSAL) licenses. Permissive licenses (Apache/MIT/BSD/PSF/MPL/ISC) pass.
An allowlist handles false positives (e.g. dual-licensed packages misreported by
classifier). Keeps the "fully open-source, on-prem-legal-clean" claim a tested property.
"""

from __future__ import annotations

import sys
from importlib.metadata import distributions

# Substrings (lower-cased) that indicate a non-permissive license.
DENY = ("gpl", "agpl", "sspl", "business source", "bsl", "rsal", "commons clause")
# GPL substring also matches LGPL; treat LGPL as allowed (weak copyleft, dynamic-link OK).
ALLOW_SUBSTR = ("lgpl",)
# Package names explicitly cleared (false positives / reviewed exceptions).
ALLOWLIST: set[str] = set()


def _license_text(dist) -> str:  # type: ignore[no-untyped-def]
    meta = dist.metadata
    parts = [meta.get("License", "") or ""]
    parts += [v for k, v in meta.items() if k == "Classifier" and "License" in v]
    return " ".join(parts).lower()


def main() -> int:
    violations: list[tuple[str, str]] = []
    for dist in distributions():
        name = (dist.metadata.get("Name") or "?").lower()
        if name in ALLOWLIST:
            continue
        text = _license_text(dist)
        if any(a in text for a in ALLOW_SUBSTR):
            continue
        if any(d in text for d in DENY):
            violations.append((name, text.strip()[:80]))

    if violations:
        print("LICENSE AUDIT FAILED — non-permissive dependencies detected (R59):")
        for name, lic in sorted(set(violations)):
            print(f"  - {name}: {lic}")
        return 1
    print("License audit passed: no copyleft / source-available dependencies.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
