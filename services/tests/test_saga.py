"""Saga orchestrator + compensation tests (R54)."""

from __future__ import annotations

import pytest
from provenance_services.saga import Ctx, Saga, SagaPause, SagaStatus, Step


def _rec(log: list[str], name: str, *, fail: bool = False, pause: bool = False):
    async def run(ctx: Ctx) -> None:
        log.append(f"run:{name}")
        if pause:
            raise SagaPause
        if fail:
            raise RuntimeError(f"{name} blew up")

    async def comp(ctx: Ctx) -> None:
        log.append(f"compensate:{name}")

    return Step(name=name, run=run, compensate=comp)


@pytest.mark.asyncio
async def test_happy_path_runs_all_steps() -> None:
    log: list[str] = []
    saga = Saga([_rec(log, "parse"), _rec(log, "write"), _rec(log, "embed")])
    out = await saga.run({})
    assert out.status is SagaStatus.DONE
    assert out.completed == ["parse", "write", "embed"]
    assert "compensate:parse" not in log


@pytest.mark.asyncio
async def test_failure_compensates_completed_steps_in_reverse() -> None:
    log: list[str] = []
    saga = Saga([
        _rec(log, "parse"),
        _rec(log, "write_graph"),
        _rec(log, "write_vectors", fail=True),  # fails here
    ])
    out = await saga.run({})
    assert out.status is SagaStatus.FAILED
    assert out.failed_step == "write_vectors"
    # Completed steps compensated in reverse order; the failed step is not compensated.
    assert out.compensated == ["write_graph", "parse"]
    assert log == [
        "run:parse", "run:write_graph", "run:write_vectors",
        "compensate:write_graph", "compensate:parse",
    ]
    assert "blew up" in (out.error or "")


@pytest.mark.asyncio
async def test_pause_parks_without_compensating() -> None:
    log: list[str] = []
    saga = Saga([
        _rec(log, "parse"),
        _rec(log, "detect", pause=True),  # detect-but-confirm pause (R9/R55)
        _rec(log, "extract"),
    ])
    out = await saga.run({})
    assert out.status is SagaStatus.PAUSED
    assert out.failed_step == "detect"
    assert "run:extract" not in log  # downstream not run
    assert not any(s.startswith("compensate") for s in log)  # pause != failure
