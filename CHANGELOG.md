# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Multi-provider LLM routing** (A2) — `LLMClient` gains an `OpenAICompatLLMClient`
  (covers vLLM / Ollama / SGLang via one OpenAI-compatible base URL) alongside the
  Anthropic (Claude) client, plus a per-task router `get_llm(task)` configured by
  `LLM_<TASK>` env. Recommended defaults: extraction → local (the token sink, on the
  Spark), planner/synthesizer → Sonnet, critic/eval-judge → Opus. The crew
  (Planner/Critic/Synthesizer) and the extraction engine are wired to the router with
  LLM paths and **heuristic fallback** — unset/no-key/no-endpoint ⇒ offline heuristic, so
  the eval gate and all tests still pass without any LLM. `anthropic` SDK added (MIT).
- **Docling default parse engine** (R60–R62) — `PARSE_ENGINE=docling` (now the default)
  runs the Docling document-understanding pipeline (layout + TableFormer + reading order)
  with **PaddleOCR (RapidOCR ONNX)** as the OCR backend, mapped onto the ParseResult
  contract (typed elements, page+bbox, reading order). Verified against the real pipeline.
  The lightweight `PARSE_ENGINE=pdfplumber` backend (digital-first + RapidOCR fallback)
  remains available for air-gap-fast / minimal-footprint deployments.
- **OCR fallback** (R60–R63) — image-only/scanned PDFs read via **RapidOCR** (ONNX
  PaddleOCR, Apache-2.0, models bundled), pages rendered by pypdfium2; OCR elements carry
  real page+bbox so citation highlight works on scans.
- **License audit hardened** — judges by SPDX classifier + license name, not the full
  license body (fixes a BSD/permissive false positive).
- **P6 (multi-vendor, minus AWS)** — Qdrant (dedicated-server) and pgvector (in-database)
  adapters behind the `VectorStorePort`, plus OpenSearch/Weaviate stubs; a config-driven
  factory selects the backend via `VECTOR_BACKEND` (R20/R21/N4). Benchmark harness +
  `docs/benchmark.md` comparing embedded (FAISS) vs server (Qdrant) vs in-DB (pgvector)
  on ingest/latency/recall (R23). pgvector verified against a real pgvector container.
  AWS deployment slice remains deferred (§12.4/12.10).
- **P5 front-end** — Next.js (TypeScript, app router) two-screen UI: **Ingest** (KB
  create with domain, upload, Quick/Full tier, status polling) and **Chat** (KB scope,
  **SSE streaming** answer, citation panel with page+bbox highlight, live entity graph,
  honest-refusal display). Gateway gains a `/query/stream` SSE endpoint (R35). The app
  type-checks and builds clean (`next build`); visual/interaction verification needs a browser.
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
