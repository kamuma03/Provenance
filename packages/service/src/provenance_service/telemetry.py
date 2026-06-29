"""OpenTelemetry wiring (R56).

One trace must span every service hop. We instrument FastAPI (inbound) and httpx
(outbound) so the W3C trace context propagates automatically across HTTP calls; NATS
propagation is handled explicitly in nats_client.py.
"""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .settings import ServiceSettings

_configured = False


def setup_telemetry(app: FastAPI, settings: ServiceSettings) -> None:
    """Configure a tracer provider + instrument FastAPI and httpx. Idempotent."""
    global _configured
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

    # FastAPI instrumentation is per-app.
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


def tracer(name: str = "provenance") -> trace.Tracer:
    return trace.get_tracer(name)
