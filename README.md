# Provenance

**A provenance-aware RAG + Knowledge Graph system where every answer traces back to a specific source span — and the system honestly refuses when the documents don't support a claim.**

Upload documents into named knowledge bases; Provenance auto-detects the domain, extracts a typed knowledge graph *and* vector embeddings, and lets you chat with grounded, citation-highlighted answers backed by multi-hop graph reasoning. Built to run **air-gapped on-premise** or on **AWS** from the same container images, on a **fully open-source, permissively-licensed** stack.

![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)
![Python](https://img.shields.io/badge/Python-3.11+-green.svg)
![Node](https://img.shields.io/badge/Node-20+-green.svg)
![Status](https://img.shields.io/badge/status-alpha%20(P0–P6%20implemented)-green.svg)

> **Status:** the full pipeline is **implemented and verified end-to-end** — ingestion
> (parse/OCR → chunk → detect → extract → graph + vectors), the retrieval + agentic-crew query
> path, and the eval gate all run on real engines. It runs **fully online with real models,
> GPU-accelerated** on the DGX Spark: ONNX embeddings (`bge-small`) and cross-encoder reranker
> (`bge-reranker-v2-m3`) on CUDA, a local LLM tier (Ollama `qwen`), and Docling/PaddleOCR parsing —
> upload a PDF and get cited, grounded answers with page + bbox. See
> **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)** for the detailed, file-by-file architecture and
> [`docs/plans/provenance-requirements.md`](docs/plans/provenance-requirements.md) for the spec.
> (The AWS deployment slice remains deferred.)

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
| Embeddings + reranker | fastembed ONNX (`bge-small` + `bge-reranker-v2-m3`) on GPU via onnxruntime-gpu |
| LLM | local tiers (Ollama `qwen`, OpenAI-compatible) with Claude as an A/B + eval judge |

Every datastore is permissively licensed (Apache 2.0 / MIT / BSD / PostgreSQL) — a CI license-audit fails the build on any SSPL/BSL/GPL component, keeping the on-prem claim legal-clean.

## Getting started

The stack runs from **layered compose overlays** — the base is hermetic (no models); overlays turn
on real models and the GPU (details in [`docs/ARCHITECTURE.md` §3](docs/ARCHITECTURE.md#3-deployment-model-compose-overlays-models-gpu)):

```bash
# Prerequisites: Docker + Docker Compose. GPU path needs an NVIDIA GPU + nvidia-container-toolkit,
# and a local Ollama serving the tier models (qwen3.6:27b / qwen3.5:9b).

# 1) Hermetic (deterministic embedder + lexical reranker, no downloads) — CI / air-gap smoke:
docker compose -f ops/docker-compose.yml up -d

# 2) Fully online with real models (LLM via host Ollama):
docker compose -f ops/docker-compose.yml -f ops/docker-compose.online.yml up -d

# 3) Fully online + ONNX models (embeddings + reranker) on GPU:
docker compose -f ops/docker-compose.yml \
               -f ops/docker-compose.online.yml \
               -f ops/docker-compose.gpu.yml up -d

# (scripts/start.sh also brings the stack up and auto-adds the Ollama tier when a GPU is present.)

# Exercise it (real cited answers on paths 2/3):
curl localhost:8000/health
KB=$(curl -s -XPOST localhost:8000/kb -d '{"name":"Demo","domain_id":"sec_financial"}'); echo $KB
curl -XPOST localhost:8000/kb/<kb_id>/documents -d '{"source":"demo.pdf","content_b64":"<base64 PDF>"}'  # 202 → saga
curl -XPOST localhost:8000/query -d '{"kb_id":"<kb_id>","query":"What revenue did the company report?"}'  # cited answer

cd web && npm install && npm run dev   # the two-screen UI at http://localhost:3000
```

Run the local checks (what CI runs):

```bash
uv pip install -e packages/contracts -e packages/service -e services
uv run pytest packages -q            # contract validation
uv run python scripts/license_audit.py   # R59: fail on non-permissive deps
```

## Repository structure

```
packages/
  contracts/   # shared domain model, ports, agent messages, domain registry (Pydantic, v1)
  service/     # shared framework: FastAPI base, OpenTelemetry, health/readiness, NATS bus
services/      # the 8 microservices (gateway, ingestion, parse, extraction, vector, graph, model, query_agent)
ops/           # docker-compose.yml, otel-collector.yaml, sql/catalog_init.sql
scripts/       # license_audit.py (R59)
tests/e2e/     # walking-skeleton end-to-end smoke test
docs/
  plans/provenance-requirements.md   # the authoritative spec (R1–R71, N1–N9)
  adr/                               # architecture decision records
```

The eval harness lives in `eval/`; the Next.js two-screen UI lives in `web/`.

## Documentation

- **[Requirements & success spec](docs/plans/provenance-requirements.md)** — the single source of truth.
- **[Architecture (overview)](ARCHITECTURE.md)** — services, data ownership, the ingestion saga.
- **[Architecture (detailed)](docs/ARCHITECTURE.md)** — file-by-file / function-by-function reference,
  the deployment model (compose overlays, models, GPU), and the end-to-end flows.
- **[ADR-001](docs/adr/ADR-001-microservices-from-p0.md)** — why full microservices from P0.
- **[Contributing](CONTRIBUTING.md)** · **[Security](SECURITY.md)** · **[Changelog](CHANGELOG.md)**

## License

[Apache-2.0](LICENSE).
