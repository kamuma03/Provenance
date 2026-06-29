"""Provenance microservices (P0 walking skeleton).

Each submodule is one service exposing a FastAPI `app`. In compose every service runs
as its own container (uniform image, per-service command). Internal calls use HTTP +
OpenTelemetry for P0; the async ingestion saga uses NATS. (gRPC migration: P1.)
"""
