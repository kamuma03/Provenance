# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **P4 eval gate** — in-process harness runs the real pipeline (chunker, FAISS, Kuzu,
  retrieval core, crew) over a self-contained eval set and gates the build on §9.2
  thresholds: numeric exact-span (R42), domain-detection accuracy (R43), honest-refusal
  + over-refusal/answer-rate (R71), retrieval recall, and a groundedness proxy.
  LLM-judged RAGAS metrics (faithfulness/relevancy/precision/recall) run on the Spark.
  CI fails below thresholds (R44). 69 unit tests incl. gate pass + regression-fail.
- **P3 agentic crew** — Planner/Critic/Synthesizer with bounded MAX_ITERATIONS loop,
  claim-level groundedness, strict whole-answer refusal, comparative set-difference.
- **P2 retrieval core** — hybrid (FAISS dense + BM25) + cross-encoder rerank + additive
  graph lift behind query(); vector floor / graph lift; empty-expansion ladder.
- **P1 ingestion** — real logic filling the saga:
  - Parse service: digital-first PDF parsing (pdfplumber) → typed elements with
    page+bbox+reading-order, tables kept coherent, parse-method provenance (R60–R64).
  - Structure-aware chunker (R68); heuristic domain detection + detect-but-confirm (R8/R9/R10/R55);
    schema-driven extraction with repair-by-dropping (R16/R17).
  - v1 entity resolver — normalized match + stable ids → cross-document merge (R18/R19).
  - Kuzu graph store (typed nodes/edges, kb_id, provenance) and FAISS VectorStorePort
    adapter + fastembed embeddings (R20–R22, R56, R66).
  - Saga orchestrator with reverse-order compensation (R54); golden-set seed + loader (R40).
  - 39 unit tests (real FAISS + Kuzu engines); CI runs the full suite + R59 license audit.
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
