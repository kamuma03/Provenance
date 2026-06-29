# ADR-001: Full microservices from P0

- **Status:** Accepted
- **Date:** 2026-06-28
- **Deciders:** kamuma03

## Context

Provenance is a single-user, provenance-aware RAG + Knowledge Graph system. The design
already uses a hexagonal/ports approach that isolates storage and model concerns behind
interfaces (e.g. `VectorStorePort`). The owner explicitly chose to build as **full
microservices from P0**, rather than a modular monolith that is later extracted.

## Decision

Decompose into **8 independently deployable services** — Gateway/BFF, Ingestion, Parse,
Extraction, Vector, Graph, Model, Query/Agent — plus a NATS message queue and a Postgres
Catalog. Adopt:

- **Database-per-service** — single owner per datastore; cross-service joins by id.
- **Async, saga-orchestrated ingestion** with compensation; **synchronous, fan-out-limited
  query** path.
- **Versioned contracts** — gRPC internally, REST/OpenAPI at the Gateway edge.
- **Distributed tracing** (OpenTelemetry); the ingestion trace *is* the provenance chain.

Stand the services up first as a **P0 walking skeleton** — thin shells with real
contracts, wired through the queue and catalog, emitting one end-to-end trace — before any
feature logic.

## Granularity rule

A service earns independence only via **a distinct resource profile** (e.g. the GPU-bound
Model service; bursty Ingestion vs steady query) **or a distinct bounded context with owned
data** (Vector, Graph, Extraction-registry, Catalog, Parse). Anything else stays merged.

Two deliberate **non-splits** that follow from this rule:
- The **4-agent crew** (Planner/Retriever/Critic/Synthesizer) stays inside one Query/Agent
  service — the agents share tight in-flight loop state; splitting would be N network hops
  per revision iteration.
- **Entity resolution** stays inside the Graph service — it writes nodes and is read by
  query-time linking, so it is cohesive with the graph's data.

## Consequences

**Positive**
- Independent scaling, especially the single GPU service.
- The same images run air-gapped (`docker compose`) and on AWS (ECS/EKS) — config-only swap.
- Provenance and distributed tracing become one artifact.
- Strong distributed-systems signal.

**Negative**
- Heavier P0: queue, Postgres, 8 containers, and contracts before the first feature demo.
- Real risk of a *distributed monolith* and of network hops eroding the latency budget.

**Mitigations**
- P0 walking skeleton front-loads integration risk.
- Database-per-service + versioned contracts prevent the distributed monolith.
- Only Query/Agent fans out; Parse is CPU-default and ingestion-only.

## Alternatives considered

- **Modular monolith with the same 8 modules behind ports, extracted to services
  phase-by-phase (Model first).** Lower upfront infrastructure, identical boundaries.
  Rejected per the owner's explicit preference for full microservices from P0.
