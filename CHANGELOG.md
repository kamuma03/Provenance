# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **P0 walking skeleton** — 8 microservices (gateway, ingestion, parse, extraction,
  vector, graph, model, query_agent) running under `docker compose` with NATS + Postgres
  + an OpenTelemetry collector. Verified: one distributed trace spans the ingestion saga
  (7 services, across the async NATS boundary) and the query fan-out (5 services).
- Shared `provenance-contracts` package (domain model, `VectorStorePort`, agent message
  contracts, domain registry) — 6/6 contract tests passing.
- Shared `provenance-service` framework (FastAPI base, OTel wiring, health/readiness, NATS bus).
- Catalog schema (`ops/sql/catalog_init.sql`), Dockerfile, docker-compose stack.
- CI workflow (ruff + mypy + pytest + R59 license-audit) and the license-audit script.
- Requirements & success specification (`docs/plans/provenance-requirements.md`):
  R1–R71 functional requirements, N1–N9 non-functional, eval-gate thresholds,
  domain catalog (10 domains, tiered), and the full microservices architecture.
- Architecture overview (`ARCHITECTURE.md`) and ADR-001 (full microservices from P0).
- Initial repository documentation: README, LICENSE (Apache-2.0), CONTRIBUTING,
  SECURITY, CLAUDE.md, `.env.example`, `.gitignore`.

## [0.1.0] - 2026-06-29

### Added
- Initial repository scaffold and documentation. No application code yet —
  implementation begins with the P0 walking skeleton.
