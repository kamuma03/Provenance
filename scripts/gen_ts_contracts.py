#!/usr/bin/env python3
"""Generate the web's shared contract types from the Pydantic contracts (N9, review M-5).

The cross-service types the UI consumes (BBox / Citation / Claim / Answer / ScoredChunk /
EvidenceSet) have a single source of truth in `provenance_contracts`. Rather than hand-copying
them into TypeScript (which drifts), we emit `web/lib/contracts.gen.ts` from the models here.

  python scripts/gen_ts_contracts.py            # (re)write the generated file
  python scripts/gen_ts_contracts.py --check    # fail if the committed file is stale (CI)
"""

from __future__ import annotations

import sys
import types
import typing
from pathlib import Path

from provenance_contracts import (
    Answer,
    BBox,
    Citation,
    Claim,
    EvidenceSet,
    ScoredChunk,
    Subgraph,
    SubgraphEdge,
    SubgraphNode,
)
from pydantic import BaseModel

# The exact set of cross-service models the web depends on, in dependency order.
MODELS: list[type[BaseModel]] = [
    BBox, Citation, ScoredChunk, Claim, Answer,
    SubgraphNode, SubgraphEdge, Subgraph, EvidenceSet,
]
OUT = Path(__file__).resolve().parents[1] / "web" / "lib" / "contracts.gen.ts"

_SCALARS = {str: "string", int: "number", float: "number", bool: "boolean"}


def _ts_type(ann: object) -> str:
    origin = typing.get_origin(ann)
    args = typing.get_args(ann)
    # Optional[X] / X | None
    if origin in (typing.Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        inner = " | ".join(_ts_type(a) for a in non_none)
        return f"{inner} | null" if len(args) > len(non_none) else inner
    if origin in (list, typing.List):  # noqa: UP006
        return f"{_ts_type(args[0])}[]"
    if origin in (dict, typing.Dict):  # noqa: UP006
        return f"Record<{_ts_type(args[0])}, {_ts_type(args[1])}>"
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return ann.__name__
    if isinstance(ann, type) and ann in _SCALARS:
        return _SCALARS[ann]
    # StrEnum and the like serialize as strings over the wire.
    if isinstance(ann, type) and issubclass(ann, str):
        return "string"
    return "unknown"


def _interface(model: type[BaseModel]) -> str:
    lines = [f"export interface {model.__name__} {{"]
    for name, field in model.model_fields.items():
        ts = _ts_type(field.annotation)
        optional = "?" if not field.is_required() else ""
        lines.append(f"  {name}{optional}: {ts};")
    lines.append("}")
    return "\n".join(lines)


def render() -> str:
    header = (
        "// AUTO-GENERATED from packages/contracts (provenance_contracts) — do NOT edit by hand.\n"
        "// Regenerate: python scripts/gen_ts_contracts.py  (CI checks this is up to date, N9).\n\n"
    )
    return header + "\n\n".join(_interface(m) for m in MODELS) + "\n"


def main() -> int:
    generated = render()
    if "--check" in sys.argv:
        current = OUT.read_text() if OUT.exists() else ""
        if current != generated:
            print(f"{OUT} is stale — run: python scripts/gen_ts_contracts.py")
            return 1
        print("web contract types are up to date with provenance_contracts.")
        return 0
    OUT.write_text(generated)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
