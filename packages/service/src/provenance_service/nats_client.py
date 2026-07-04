"""NATS bus with explicit W3C trace-context propagation (R54, R56).

HTTP propagation is automatic via instrumentation; for the async saga we inject the
trace context into message headers on publish and extract it on receive, so the
ingestion trace stays unbroken across the queue.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress

import nats
from nats.aio.client import Client as NatsConn
from nats.aio.msg import Msg
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagate import extract, inject

from .telemetry import tracer

log = logging.getLogger("nats")
MessageHandler = Callable[[bytes, dict[str, str]], Awaitable[None]]


class NatsBus:
    """Thin NATS wrapper that carries the trace context across publish/subscribe.

    Supports two delivery modes: core pub/sub (at-most-once, for transient status events)
    and JetStream durable consumers (at-least-once with explicit ack, for the ingest saga —
    a consumer crash mid-saga redelivers the job rather than losing it, review H-3). When the
    server has no JetStream, the durable methods degrade to core so tests/air-gap still run.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._conn: NatsConn | None = None
        self._js: object | None = None

    async def connect(self) -> None:
        self._conn = await nats.connect(self._url)
        try:
            self._js = self._conn.jetstream()
        except Exception:  # pragma: no cover - server without -js
            self._js = None

    async def ensure_stream(self, name: str, subjects: list[str]) -> None:
        """Idempotently declare a JetStream stream covering `subjects` (no-op on core)."""
        if self._js is None:
            return
        with suppress(Exception):  # already exists / not permitted → keep going
            await self._js.add_stream(name=name, subjects=subjects)  # type: ignore[attr-defined]

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.drain()

    @property
    def connected(self) -> bool:
        return self._conn is not None and self._conn.is_connected

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        inject(headers)  # serialize the active span context into headers (R56)
        return headers

    async def publish(self, subject: str, payload: bytes) -> None:
        """Core publish — at-most-once. For transient events (status updates)."""
        assert self._conn is not None, "bus not connected"
        with tracer().start_as_current_span(f"publish {subject}", kind=trace.SpanKind.PRODUCER):
            await self._conn.publish(subject, payload, headers=self._headers())

    async def publish_durable(self, subject: str, payload: bytes) -> None:
        """JetStream publish — persisted, so a queued job survives a consumer restart (H-3).
        Falls back to core when JetStream is unavailable."""
        assert self._conn is not None, "bus not connected"
        with tracer().start_as_current_span(f"publish {subject}", kind=trace.SpanKind.PRODUCER):
            if self._js is not None:
                await self._js.publish(subject, payload, headers=self._headers())  # type: ignore[attr-defined]
            else:
                await self._conn.publish(subject, payload, headers=self._headers())

    def _traced_handler(
        self, subject: str, handler: MessageHandler
    ) -> Callable[[Msg], Awaitable[None]]:
        async def _run(msg: Msg) -> None:
            headers = dict(msg.headers or {})
            token = otel_context.attach(extract(headers))
            try:
                with tracer().start_as_current_span(
                    f"consume {subject}", kind=trace.SpanKind.CONSUMER
                ):
                    await handler(msg.data, headers)
            finally:
                otel_context.detach(token)
        return _run

    async def subscribe(self, subject: str, handler: MessageHandler, queue: str = "") -> None:
        assert self._conn is not None, "bus not connected"
        run = self._traced_handler(subject, handler)

        async def _cb(msg: Msg) -> None:
            await run(msg)

        await self._conn.subscribe(subject, cb=_cb, queue=queue)

    async def subscribe_durable(
        self, subject: str, handler: MessageHandler, *, durable: str, queue: str = ""
    ) -> None:
        """Durable JetStream consumer: ack ONLY after the handler completes, so a crash
        mid-processing redelivers the message instead of dropping it (H-3). Degrades to a
        core subscription when JetStream is unavailable."""
        assert self._conn is not None, "bus not connected"
        if self._js is None:
            await self.subscribe(subject, handler, queue)
            return
        run = self._traced_handler(subject, handler)

        async def _cb(msg: Msg) -> None:
            try:
                await run(msg)
            except Exception:  # handler blew up — leave unacked so JetStream redelivers
                log.exception("durable handler failed for %s; will redeliver", subject)
                with suppress(Exception):
                    await msg.nak()
                return
            with suppress(Exception):
                await msg.ack()  # saga completed → safe to remove the job from the stream

        await self._js.subscribe(  # type: ignore[attr-defined]
            subject, durable=durable, cb=_cb, manual_ack=True
        )
