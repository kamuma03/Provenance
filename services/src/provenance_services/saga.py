"""Saga orchestrator with compensation (R54).

Runs ingestion steps in order. On failure, the already-completed steps are compensated
in reverse order and the document ends `failed` — never half-ingested. A step may raise
SagaPause to park the saga (detect-but-confirm, R9/R55) without compensating.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel

log = logging.getLogger("saga")

Ctx = dict[str, object]
StepFn = Callable[[Ctx], Awaitable[None]]
# (step_name, state) -> None; state ∈ {active, done, blocked, failed}. Lets the orchestrator
# publish per-stage progress for the saga stepper (R-BE-6) without the steps knowing about it.
StepHook = Callable[[str, str], Awaitable[None]]


class SagaPause(Exception):  # noqa: N818 - control signal, not an error
    """Raised by a step to pause the saga (awaiting external confirmation)."""


class SagaStatus(StrEnum):
    DONE = "done"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class Step:
    name: str
    run: StepFn
    compensate: StepFn | None = None


class SagaOutcome(BaseModel):
    status: SagaStatus
    completed: list[str]
    compensated: list[str]
    failed_step: str | None = None
    error: str | None = None


class Saga:
    def __init__(self, steps: list[Step], on_step: StepHook | None = None) -> None:
        self._steps = steps
        self._on_step = on_step

    async def _emit(self, name: str, state: str) -> None:
        """Best-effort progress signal — a hook failure must never derail the saga (M-11)."""
        if self._on_step is None:
            return
        try:
            await self._on_step(name, state)
        except Exception as exc:  # noqa: BLE001 - progress is advisory, not load-bearing
            log.warning("saga on_step(%s, %s) failed: %s", name, state, exc)

    async def run(self, ctx: Ctx) -> SagaOutcome:
        completed: list[Step] = []
        for step in self._steps:
            await self._emit(step.name, "active")
            try:
                await step.run(ctx)
            except SagaPause:
                await self._emit(step.name, "blocked")
                return SagaOutcome(
                    status=SagaStatus.PAUSED,
                    completed=[s.name for s in completed],
                    compensated=[],
                    failed_step=step.name,
                )
            except Exception as exc:  # noqa: BLE001 - saga must catch all to compensate
                await self._emit(step.name, "failed")
                compensated: list[str] = []
                for done in reversed(completed):
                    if done.compensate is not None:
                        try:
                            await done.compensate(ctx)
                            compensated.append(done.name)
                        except Exception as comp_exc:  # noqa: BLE001 - best-effort rollback
                            # A failed rollback can leave orphaned state; never hide it (M-12).
                            log.warning("compensation for step %s failed: %s",
                                        done.name, comp_exc)
                return SagaOutcome(
                    status=SagaStatus.FAILED,
                    completed=[s.name for s in completed],
                    compensated=compensated,
                    failed_step=step.name,
                    error=str(exc),
                )
            completed.append(step)
            await self._emit(step.name, "done")
        return SagaOutcome(
            status=SagaStatus.DONE, completed=[s.name for s in completed], compensated=[]
        )
