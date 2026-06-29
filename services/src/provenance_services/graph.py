"""Graph service — Kuzu LPG, entity resolution, graph expansion (R22, R18, R27).

P0: no-op shell. Kuzu writes + additive expansion land in P1/P2.
"""

from __future__ import annotations

from provenance_service import create_app, tracer

app = create_app("graph")


@app.post("/write", tags=["graph"])
async def write() -> dict[str, object]:
    with tracer("graph").start_as_current_span("graph.write"):
        return {"ok": True, "merged_entities": 0, "note": "P0 skeleton no-op"}


@app.post("/expand", tags=["graph"])
async def expand() -> dict[str, object]:
    with tracer("graph").start_as_current_span("graph.expand"):
        # Vector floor / graph lift: expansion is additive (R25).
        return {"entities": [], "note": "P0 skeleton no-op"}
