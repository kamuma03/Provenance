"""Shared service settings, sourced from the environment (see .env.example, N4)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    service_name: str = "provenance-service"
    # OpenTelemetry (R56). Empty endpoint => tracing stays local (no exporter).
    otel_exporter_otlp_endpoint: str = ""
    otel_service_namespace: str = "provenance"
    # Async bus (R54).
    nats_url: str = "nats://nats:4222"
