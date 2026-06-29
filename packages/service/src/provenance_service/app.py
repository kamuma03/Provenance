"""create_app — the FastAPI base every service is built on (R51, R69).

Provides liveness/readiness endpoints and OpenTelemetry wiring out of the box, so each
service shell is genuinely uniform.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .settings import ServiceSettings
from .telemetry import setup_telemetry

ReadinessCheck = Callable[[], Awaitable[bool]]


def create_app(
    service_name: str,
    *,
    settings: ServiceSettings | None = None,
    readiness: ReadinessCheck | None = None,
    on_startup: Callable[[], Awaitable[None]] | None = None,
    on_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> FastAPI:
    cfg = settings or ServiceSettings(service_name=service_name)

    @asynccontextmanager
    async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
        if on_startup is not None:
            await on_startup()
        yield
        if on_shutdown is not None:
            await on_shutdown()

    app = FastAPI(title=service_name, version="0.1.0", lifespan=lifespan)
    setup_telemetry(app, cfg)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        """Liveness (R69): the process is up."""
        return {"status": "ok", "service": service_name}

    @app.get("/ready", tags=["ops"])
    async def ready() -> JSONResponse:
        """Readiness (R69): dependencies are reachable. Degrades gracefully (N6)."""
        ok = True if readiness is None else await readiness()
        return JSONResponse(
            status_code=200 if ok else 503,
            content={"ready": ok, "service": service_name},
        )

    return app


def traced_client(timeout: float = 10.0) -> httpx.AsyncClient:
    """An httpx client whose calls propagate the trace context (instrumented globally)."""
    return httpx.AsyncClient(timeout=timeout)
