# Architecture

This is the design overview. The authoritative, requirement-level source is
[`docs/plans/provenance-requirements.md`](docs/plans/provenance-requirements.md)
(R1–R71, N1–N9, Appendices A–C). Decisions are recorded as ADRs in [`docs/adr/`](docs/adr/).

## Two sub-domains

The system is split into two bounded contexts, integrated only at the query boundary.

**Knowledge sub-domain (ingestion)**
```
KnowledgeBase (id, name, domain_id) ─OWNS─► Document ─CONTAINS─► Chunk (page, bbox)
                                                          └─MENTIONS─► Entity
Entity ─RELATES_TO─► Entity        (typed edge in Kuzu)
Document ─PROVENANCE─► Entity        (every fact traces to a source)
```

**Interaction sub-domain (query)**
```
Query ─DECOMPOSES_TO─► Subquery (factual | relational | comparative)
                        └─RESOLVES_TO─► EvidenceSet (chunks, entities, scores)
Answer ─CITES─► Chunk (page + bbox)        Critic ─VERIFIES─► Answer
```

## Services (8) — microservices from P0

```
Next.js UI
   │ HTTP + SSE
Gateway / BFF ──────────► Catalog (Postgres): KB / Document / Chunk + provenance + trace_id
   ├─ async (NATS) ─► Ingestion (saga orchestrator + compensation)
   │                     └─► Parse · Extraction · Graph · Model · Vector
   └─ sync  (gRPC) ─► Query / Agent (retrieval core + AutoGen crew)
                         └─► Vector · Graph · Model
```

| Service | Owns | Responsibility | Profile |
|---|---|---|---|
| Gateway / BFF | Catalog (Postgres) | SSE edge, routing, ingestion-saga orchestration | CPU, stateless edge |
| Ingestion | — | Async workers; structure-aware chunking; saga + compensation | CPU, bursty |
| Parse | OCR/layout models | Layout-aware OCR, table structure, reading order, bbox (Docling + PaddleOCR) | CPU-default, ingestion-only |
| Extraction | Domain registry | Domain detection + schema-driven extraction | LLM-bound |
| Vector | Vector indices | `VectorStorePort`: FAISS / Qdrant / pgvector | stateful |
| Graph | Kuzu LPG | Typed nodes/edges, entity resolution, graph expansion | stateful |
| Model | model weights | Embeddings + cross-encoder reranker | **GPU** (only one) |
| Query / Agent | — | Retrieval core (`query()`) + Planner/Retriever/Critic/Synthesizer | LLM + CPU |

Two deliberate **non-splits**: the 4-agent crew lives in one Query/Agent service, and
entity resolution lives inside Graph (see ADR-001).

## Key invariants

- **Database-per-service (R52)** — single owner per store; join by id over the wire.
- **Vector floor, graph lift (R25)** — every subquery gets vector retrieval; graph
  expansion is additive, never graph-only. Empty expansion degrades down a ladder (R27).
- **Strict groundedness (R31/R32)** — an answer with any ungrounded claim is never
  released; on revision exhaustion the system refuses honestly.
- **Provenance == tracing (R56)** — W3C trace context flows through every hop; the
  ingestion trace *is* the document's provenance chain (detected → parsed → extracted →
  embedded → stored).
- **Permissive licenses only (R59)** — CI license-audit fails on any SSPL/BSL/GPL component.

## Ingestion saga (orchestration + compensation)

```
Gateway: Document(queued) → enqueue → 202
Ingestion worker (orchestrator):
  1. parse (layout/OCR/table)      → Parse        → structure-aware chunk
  2. detect domain                 → Extraction
  3. SAGA PAUSE: await confirm/override            (detect-but-confirm)
  4. extract entities/relations    → Extraction
  5. resolve + write graph         → Graph
  6. embed + write vectors         → Model + Vector
  7. Document(done) + provenance + trace_id → Catalog
On failure → compensate (roll back partial writes), Document(failed). No half-ingest.
```

## Query path (synchronous, fan-out-limited)

Gateway → Query/Agent → fan-out to Vector + Graph + Model (gRPC). Only Query/Agent fans
out (R53). Tokens stream back via SSE at the edge. The Planner types each subquery and
routes relational/comparative work to additive graph expansion; the Critic verifies
groundedness claim-by-claim; the Synthesizer composes the cited answer.

## Deployment

Same images, two targets (R58): `docker compose up` air-gapped on the DGX Spark, or
ECS/EKS on AWS (managed equivalents swapped by config). See Appendix B.7 of the spec.

## Tech stack

Python/FastAPI services · Next.js/TypeScript UI · LlamaIndex (retrieval) · AutoGen
(agents) · Kuzu (graph) · Postgres + FAISS/Qdrant/pgvector (data) · NATS (queue) ·
Docling + PaddleOCR (parsing) · RAGAS (eval) · OpenTelemetry (tracing) · Claude (LLM).
