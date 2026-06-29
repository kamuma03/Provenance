"""Saga orchestrator with compensation (R54).

Runs ingestion steps in order. On failure, the already-completed steps are compensated
in reverse order and the document ends `failed` — never half-ingested. A step may raise
SagaPause to park the saga (detect-but-confirm, R9/R55) without compensating.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel

Ctx = dict[str, object]
StepFn = Callable[[Ctx], Awaitable[None]]


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
    def __init__(self, steps: list[Step]) -> None:
        self._steps = steps

    async def run(self, ctx: Ctx) -> SagaOutcome:
        completed: list[Step] = []
        for step in self._steps:
            try:
                await step.run(ctx)
            except SagaPause:
                return SagaOutcome(
                    status=SagaStatus.PAUSED,
                    completed=[s.name for s in completed],
                    compensated=[],
                    failed_step=step.name,
                )
            except Exception as exc:  # noqa: BLE001 - saga must catch all to compensate
                compensated: list[str] = []
                for done in reversed(completed):
                    if done.compensate is not None:
                        try:
                            await done.compensate(ctx)
                            compensated.append(done.name)
                        except Exception:  # noqa: BLE001 - best-effort rollback
                            pass
                return SagaOutcome(
                    status=SagaStatus.FAILED,
                    completed=[s.name for s in completed],
                    compensated=compensated,
                    failed_step=step.name,
                    error=str(exc),
                )
            completed.append(step)
        return SagaOutcome(
            status=SagaStatus.DONE, completed=[s.name for s in completed], compensated=[]
        )
