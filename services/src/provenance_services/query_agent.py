"""Query/Agent service — retrieval core + the 4-agent crew (R29–R33, R53).

P0: no-op shell that fans out to Model + Vector + Graph (proving the query trace spans
services) and returns a skeleton Answer. Only this service fans out (R53).
"""

from __future__ import annotations

from fastapi import Request
from provenance_contracts import Answer
from provenance_service import create_app, tracer

from .clients import call

app = create_app("query-agent")


@app.post("/answer", tags=["query"])
async def answer(req: Request) -> dict[str, object]:
    body = await req.json()
    query_text = body.get("query", "")
    with tracer("query-agent").start_as_current_span("query.answer"):
        # P0 fan-out (R53): embed → vector search → additive graph lift. All no-ops.
        await call("model", "/embed")
        await call("vector", "/query")
        await call("graph", "/expand")
        ans = Answer(text="(P0 skeleton — no feature logic yet)", refused=False)
    return {"query": query_text, "answer": ans.model_dump()}
