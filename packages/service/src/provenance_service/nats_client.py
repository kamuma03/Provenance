"""NATS bus with explicit W3C trace-context propagation (R54, R56).

HTTP propagation is automatic via instrumentation; for the async saga we inject the
trace context into message headers on publish and extract it on receive, so the
ingestion trace stays unbroken across the queue.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import nats
from nats.aio.client import Client as NatsConn
from nats.aio.msg import Msg
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagate import extract, inject

from .telemetry import tracer

MessageHandler = Callable[[bytes, dict[str, str]], Awaitable[None]]


class NatsBus:
    """Thin NATS wrapper that carries the trace context across publish/subscribe."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._conn: NatsConn | None = None

    async def connect(self) -> None:
        self._conn = await nats.connect(self._url)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.drain()

    @property
    def connected(self) -> bool:
        return self._conn is not None and self._conn.is_connected

    async def publish(self, subject: str, payload: bytes) -> None:
        assert self._conn is not None, "bus not connected"
        headers: dict[str, str] = {}
        inject(headers)  # serialize the active span context into headers
        with tracer().start_as_current_span(f"publish {subject}", kind=trace.SpanKind.PRODUCER):
            inject(headers)
            await self._conn.publish(subject, payload, headers=headers)

    async def subscribe(self, subject: str, handler: MessageHandler, queue: str = "") -> None:
        assert self._conn is not None, "bus not connected"

        async def _cb(msg: Msg) -> None:
            headers = dict(msg.headers or {})
            ctx = extract(headers)
            token = otel_context.attach(ctx)
            try:
                with tracer().start_as_current_span(
                    f"consume {subject}", kind=trace.SpanKind.CONSUMER
                ):
                    await handler(msg.data, headers)
            finally:
                otel_context.detach(token)

        await self._conn.subscribe(subject, cb=_cb, queue=queue)
