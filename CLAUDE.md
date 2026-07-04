# CLAUDE.md

Guidance for AI agents (and humans) working in this repository.

## What this project is

**Provenance** — a provenance-aware RAG + Knowledge Graph system. Every answer traces to a
source span (page + bbox); the system refuses honestly when the corpus doesn't support a
claim. Two surfaces: document **ingestion** (auto domain-detection + OCR → graph + vectors)
and **chat** (agentic, cited, multi-hop).

## Read this first

- **[`docs/plans/provenance-requirements.md`](docs/plans/provenance-requirements.md)** is the
  single source of truth — R1–R71 (functional), N1–N9 (non-functional), eval-gate
  thresholds (§9.2), the domain catalog (Appendix A), service architecture (Appendix B),
  and the datastore/license policy (Appendix C). Every requirement has a testable
  acceptance criterion; "done" = its criterion is green.
- **[`ARCHITECTURE.md`](ARCHITECTURE.md)** — the service map and saga.
- **[`docs/adr/`](docs/adr/)** — decisions and their rationale.

## Status & where to start

The walking skeleton and the P1–P5 slices are **implemented**: 8 services, saga-orchestrated
ingestion, layout-aware parse (Docling / pdfplumber + OCR), domain detection + extraction,
Kuzu graph, hybrid retrieval + rerank + additive graph lift, the 4-agent crew, the Next.js UI,
end-to-end OpenTelemetry tracing, a CI license-audit, and an offline eval gate. **Deferred**
(documented, not yet coded): gRPC transport (currently HTTP/JSON with shared Pydantic contracts),
NATS JetStream durability + real saga compensation, RAGAS LLM-judged metrics, and the P6
AWS adapters. See [`docs/plans/remediation-plan.md`](docs/plans/remediation-plan.md) for the
open review findings and their sequencing.

## Invariants — do not violate

1. **Database-per-service** (R52) — no shared datastores; join by id over the wire.
2. **Permissive licenses only** (R59) — Apache-2.0/MIT/BSD/PostgreSQL/MPL. No SSPL/BSL/GPL.
   This filters datastores *and* OCR/models (it's why Surya/Nougat/MinerU are rejected).
3. **Vector floor, graph lift** (R25) — never route to graph-only; expansion is additive.
4. **Strict groundedness** (R31/R32) — never release an answer with any ungrounded claim;
   refuse honestly on revision exhaustion. The Critic distinguishes "ungrounded" from
   "correctly grounded in an absence."
5. **Bounded loops** (R32) — the Planner→Critic loop has a hard `MAX_ITERATIONS`.
6. **Provenance + tracing** (R56) — propagate W3C trace context; record how each fact was
   extracted (domain, confidence, schema version, parse method).
7. **Shared contracts** (R57, N9) — one source of truth for cross-service types; never
   hand-copy them. Internal transport is HTTP/JSON with shared Pydantic contracts today;
   gRPC (R57) is deferred.
8. **Two non-splits** (ADR-001) — keep the agent crew in one service; keep entity
   resolution in Graph.

## Conventions

- Python services: `ruff` + `mypy`, `pytest`. TypeScript UI: `eslint` + `tsc`.
- Conventional Commits, referencing requirement IDs (e.g. `feat(parse): tables (R62)`).
- Reference machine for all latency/scale numbers is the **DGX Spark** (A8).
- Keep changes inside the owning service; surface any contract/schema change explicitly.

## What not to do

- Don't add a 5th agent or split the crew into services.
- Don't introduce a non-permissive dependency (the CI license-audit will fail).
- Don't make retrieval graph-only, or release partial/ungrounded answers.
- Don't expand scope beyond the spec's §1 — check the out-of-scope list before building.
