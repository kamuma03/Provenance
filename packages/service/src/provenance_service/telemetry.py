"""OpenTelemetry wiring (R56).

One trace must span every service hop. We instrument FastAPI (inbound) and httpx
(outbound) so the W3C trace context propagates automatically across HTTP calls; NATS
propagation is handled explicitly in nats_client.py.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .settings import ServiceSettings

log = logging.getLogger("telemetry")
_configured = False
_configured_service: str | None = None


def setup_telemetry(app: FastAPI, settings: ServiceSettings) -> None:
    """Configure a tracer provider + instrument FastAPI and httpx. Idempotent.

    The OTel TracerProvider carries a single ``service.name`` per process. Each service runs
    in its own container, so that's correct in production — but if a *second* app with a
    different name is set up in the same process (e.g. an in-process multi-app harness), its
    spans would be silently misattributed to the first identity. We surface that with a
    warning rather than binding invisibly (review M-16).
    """
    global _configured, _configured_service
    if _configured and _configured_service != settings.service_name:
        log.warning(
            "telemetry already configured as service.name=%r; spans from %r in this process "
            "will be attributed to the first identity",
            _configured_service, settings.service_name,
        )
    if not _configured:
        resource = Resource.create(
            {
                "service.name": settings.service_name,
                "service.namespace": settings.otel_service_namespace,
            }
        )
        provider = TracerProvider(resource=resource)
        if settings.otel_exporter_otlp_endpoint:
            # Imported lazily so the package works without the exporter configured.
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
                )
            )
        trace.set_tracer_provider(provider)

        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
        _configured = True
        _configured_service = settings.service_name

    # FastAPI instrumentation is per-app.
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


def tracer(name: str = "provenance") -> trace.Tracer:
    return trace.get_tracer(name)
