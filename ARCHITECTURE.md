# Architecture

This is the design overview. For the **detailed, file-by-file / function-by-function reference**
(plus the deployment model — compose overlays, models, GPU — and end-to-end flows) see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The authoritative, requirement-level source is
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
| Model | model weights | Embeddings (`bge-small`) + cross-encoder reranker (`bge-reranker-v2-m3`), both ONNX | **GPU** |
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

Same image (one multi-stage `Dockerfile`), layered **compose overlays** (details in
[`docs/ARCHITECTURE.md` §3](docs/ARCHITECTURE.md#3-deployment-model-compose-overlays-models-gpu)):

- **base** (`ops/docker-compose.yml`) — hermetic: deterministic embedder + lexical reranker, no
  model downloads. CI / air-gap smoke.
- **+ online** (`docker-compose.online.yml`) — real fastembed embeddings + reranker; LLM via the
  host Ollama.
- **+ gpu** (`docker-compose.gpu.yml`) — the ONNX models (embeddings + reranker; OCR) on CUDA via
  `onnxruntime-gpu`, GPU granted to `model`/`query-agent`/`parse`.

The onnxruntime-gpu wheel is aarch64/CUDA-13 (the reference machine is the DGX Spark); the image
build guards the GPU swap by `TARGETARCH`, so an x86 build falls back cleanly to CPU onnxruntime.
Same images also target ECS/EKS on AWS (managed equivalents by config, R58 — deferred slice).

## Tech stack

Python/FastAPI services · Next.js/TypeScript UI · hybrid retrieval (FAISS + BM25 RRF) + cross-encoder
rerank · a 4-agent crew (Planner/Retriever/Critic/Synthesizer) · Kuzu (graph) · Postgres +
FAISS/Qdrant/pgvector (data) · NATS (queue) · Docling + PaddleOCR/RapidOCR (parsing) · fastembed +
onnxruntime-gpu (`bge-small` + `bge-reranker-v2-m3`) · local LLM tiers (Ollama `qwen`,
OpenAI-compatible) with Claude as A/B + eval judge · RAGAS (eval) · OpenTelemetry (tracing).
