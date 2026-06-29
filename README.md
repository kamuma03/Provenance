# Provenance

**A provenance-aware RAG + Knowledge Graph system where every answer traces back to a specific source span — and the system honestly refuses when the documents don't support a claim.**

Upload documents into named knowledge bases; Provenance auto-detects the domain, extracts a typed knowledge graph *and* vector embeddings, and lets you chat with grounded, citation-highlighted answers backed by multi-hop graph reasoning. Built to run **air-gapped on-premise** or on **AWS** from the same container images, on a **fully open-source, permissively-licensed** stack.

![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)
![Python](https://img.shields.io/badge/Python-3.11+-green.svg)
![Node](https://img.shields.io/badge/Node-20+-green.svg)
![Status](https://img.shields.io/badge/status-pre--alpha%20(planning%20complete)-orange.svg)

> **Status:** Greenfield. The complete requirements & architecture specification is finished
> ([`docs/plans/provenance-requirements.md`](docs/plans/provenance-requirements.md)); implementation
> begins with the **P0 walking skeleton**. Commands below marked _(P0)_ are not wired yet.

---

## Why it exists

Most RAG demos answer plausibly and cite nothing — or cite something that doesn't say what the answer claims. Provenance treats **traceability as a first-class property**:

- **Every fact traces to a source.** Answers carry citations down to the page and bounding box; click a citation to highlight the exact span.
- **Multi-hop, not just lookup.** A typed knowledge graph (Kuzu) sits beside the vector store, so relational and comparative questions ("which risk factors did X cite in 2022 but not 2021?") are answerable — vanilla RAG can't.
- **Honest refusal.** A Critic agent verifies groundedness claim-by-claim; if the corpus doesn't support an answer, the system says so instead of fabricating.
- **Provenance includes *how* a fact was extracted** — detected domain, confidence, schema version, OCR method — all recorded and correlated to a distributed trace.

## What it does

Two surfaces, mapped to two sub-domains:

1. **Ingestion** — upload a document → layout-aware OCR (Docling + PaddleOCR) → auto domain-detection (detect-but-confirm) → typed extraction into a knowledge graph + vector embeddings, partitioned per knowledge base.
2. **Chat** — ask questions → an agentic crew (Planner → Retriever → Critic → Synthesizer) plans, retrieves (hybrid + rerank + additive graph expansion), verifies groundedness, and streams a cited answer with a live entity graph.

## Architecture

A microservices system (8 services) with **database-per-service**, an async saga-orchestrated ingestion pipeline, a synchronous query path, and distributed tracing. See [`ARCHITECTURE.md`](ARCHITECTURE.md) and [ADR-001](docs/adr/ADR-001-microservices-from-p0.md).

```
Next.js UI ──SSE──► Gateway/BFF ──┬─ async (NATS) ─► Ingestion ─► Parse · Extraction · Graph · Model · Vector
                                  └─ sync (gRPC) ───► Query/Agent ─► Vector · Graph · Model
```

| Concern | Choice (open-source, permissive) |
|---|---|
| Catalog (metadata + provenance) | PostgreSQL |
| Vector store | FAISS · Qdrant · pgvector (behind one `VectorStorePort`) |
| Knowledge graph | Kuzu (MIT) |
| Message queue | NATS JetStream |
| OCR / parsing | Docling + PaddleOCR |
| Retrieval | LlamaIndex (hybrid + rerank + graph expansion) |
| Agents | AutoGen (Planner / Retriever / Critic / Synthesizer) |
| Eval | RAGAS + hallucination + domain-detection accuracy, as a CI gate |
| LLM | Claude (configurable endpoint) |

Every datastore is permissively licensed (Apache 2.0 / MIT / BSD / PostgreSQL) — a CI license-audit fails the build on any SSPL/BSL/GPL component, keeping the on-prem claim legal-clean.

## Getting started _(P0)_

```bash
# Prerequisites: Docker + Docker Compose, a configured LLM endpoint
cp .env.example .env          # then edit credentials/endpoints
docker compose up             # brings up all 8 services + NATS + Postgres   (P0)
```

The first milestone (P0) is a *walking skeleton*: all services as thin shells wired through the queue and catalog, emitting one end-to-end trace, before any feature logic.

## Repository structure

```
docs/
  plans/provenance-requirements.md   # the authoritative spec (R1–R71, N1–N9)
  adr/                               # architecture decision records
ARCHITECTURE.md                      # service map & design overview
CONTRIBUTING.md  SECURITY.md  CHANGELOG.md  CLAUDE.md
```

Service code (`services/`), the Next.js app (`web/`), and the eval harness (`eval/`) land during P0–P5.

## Documentation

- **[Requirements & success spec](docs/plans/provenance-requirements.md)** — the single source of truth.
- **[Architecture](ARCHITECTURE.md)** — services, data ownership, the ingestion saga.
- **[ADR-001](docs/adr/ADR-001-microservices-from-p0.md)** — why full microservices from P0.
- **[Contributing](CONTRIBUTING.md)** · **[Security](SECURITY.md)** · **[Changelog](CHANGELOG.md)**

## License

[Apache-2.0](LICENSE).
