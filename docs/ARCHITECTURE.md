# Provenance — Detailed Architecture

This is the deep, file-by-file reference for the Provenance system: what every service,
module, and function does, how the ingestion and query flows work end-to-end, and how the
system is deployed fully-online with GPU-accelerated models.

- The **design-level** overview is [`../ARCHITECTURE.md`](../ARCHITECTURE.md).
- The **authoritative requirements** are [`plans/provenance-requirements.md`](plans/provenance-requirements.md)
  (R1–R71, N1–N9, Appendices A–C). Requirement IDs in this document (e.g. `R25`) point there.
- **Decisions** are recorded as ADRs in [`adr/`](adr/).

---

## 1. What the system is

Provenance is a **provenance-aware RAG + Knowledge-Graph** system. Two surfaces:

1. **Ingestion** — upload a document → layout-aware parse/OCR → auto domain-detection →
   typed extraction into a **knowledge graph (Kuzu)** *and* **vector embeddings**, partitioned
   per knowledge base.
2. **Chat** — ask a question → an agentic crew (Planner → Retriever → Critic → Synthesizer)
   plans, retrieves (hybrid + rerank + additive graph expansion), verifies groundedness
   claim-by-claim, and returns a **cited** answer — or **refuses honestly** when the corpus
   doesn't support it.

Two non-negotiable properties drive the design:

- **Traceability.** Every released claim carries a citation down to `page + bounding box`.
  The ingestion path records *how* each fact was produced (detected domain, confidence,
  schema version, parse method) and correlates it to a distributed trace (R56).
- **Honest refusal.** An answer with any ungrounded claim is never released; on revision
  exhaustion the system refuses (R31/R32).

### Core invariants (do not violate)

| # | Invariant | Where enforced |
|---|---|---|
| R52 | **Database-per-service** — no shared datastores; join by id over the wire | each service owns its store |
| R59 | **Permissive licenses only** (Apache/MIT/BSD/PostgreSQL/MPL) | `scripts/license_audit.py` in CI |
| R25 | **Vector floor, graph lift** — never route graph-only; expansion is additive | `retrieval.py::retrieve` |
| R31/R32 | **Strict groundedness** — refuse rather than release ungrounded claims | `crew.py::Critic`, `run_crew` |
| R32 | **Bounded loops** — Planner→Critic loop has a hard `MAX_ITERATIONS` | `crew.py::run_crew` |
| R56 | **Provenance == tracing** — W3C trace context on every hop | `telemetry.py`, `nats_client.py` |
| ADR-001 | **Two non-splits** — crew stays in one service; entity resolution stays in Graph | `crew.py`, `graph.py`/`resolver.py` |

---

## 2. Topology at a glance

```
                         Next.js UI (web/)  ── HTTP + SSE ──►  Gateway / BFF  ── owns ──► Catalog (Postgres)
                                                                    │
                        ┌──────────────── async (NATS JetStream) ───┤
                        ▼                                            │
                   Ingestion (saga orchestrator + compensation)     └── sync (HTTP) ──► Query / Agent
                        │                                                                    │
        ┌────────┬──────┴─────┬─────────┬─────────┐                          ┌──────────────┼───────────────┐
        ▼        ▼            ▼         ▼         ▼                          ▼              ▼               ▼
      Parse   Extraction    Graph     Model    Vector                     Vector          Graph           Model
   (Docling/  (detect +   (Kuzu +   (embed +  (FAISS/                   (hybrid)    (link + expand)   (embed + rerank)
    OCR/table) schema-     resolve)  rerank)   Qdrant/
               extraction)  GPU       GPU      pgvector)                                                    GPU
```

**8 services**, all built from **one image** (`Dockerfile`) with a per-service command in
`ops/docker-compose.yml`. Only **Query/Agent** fans out on the query path (R53); only
**Ingestion** orchestrates the saga (R54).

| Service | Module | Owns | Responsibility | GPU |
|---|---|---|---|---|
| Gateway / BFF | `gateway.py` | Catalog (Postgres) | REST/SSE edge, KB/upload/query routing, saga entry, status | no |
| Ingestion | `ingestion.py` | — | Async saga worker: parse→chunk→detect→extract→graph→embed→vector | no |
| Parse | `parse.py` | OCR/layout models | Layout-aware parse, tables, reading order, bbox | **yes** (OCR ONNX) |
| Extraction | `extraction.py` | Domain registry | Domain detection + schema-driven entity/relation extraction | LLM-bound |
| Graph | `graph.py` | Kuzu graph | Typed nodes/edges, entity resolution, link + expand | no |
| Model | `model.py` | model weights | Embeddings **and** cross-encoder reranker | **yes** (both ONNX) |
| Vector | `vector.py` | vector index | `VectorStorePort`: FAISS / Qdrant / pgvector | no |
| Query / Agent | `query_agent.py` | — | Retrieval core + Planner/Retriever/Critic/Synthesizer crew | LLM-bound |

---

## 3. Deployment model (compose overlays, models, GPU)

The stack runs from **layered compose files**. The base is hermetic (no network, no models);
overlays progressively turn on real models and the GPU.

```bash
# hermetic (deterministic embedder + lexical reranker, no model downloads) — CI/air-gap smoke
docker compose -f ops/docker-compose.yml up -d

# fully online (real models; LLM via host Ollama)
docker compose -f ops/docker-compose.yml -f ops/docker-compose.online.yml up -d

# fully online + ONNX models on GPU
docker compose -f ops/docker-compose.yml \
               -f ops/docker-compose.online.yml \
               -f ops/docker-compose.gpu.yml up -d
```

| File | Role |
|---|---|
| `ops/docker-compose.yml` | Base: 8 services + NATS + Postgres + OTel collector. `PROVENANCE_OFFLINE=1` (hermetic). LLM tier names + routing env. Ollama + `ollama-pull` are profile-gated (`--profile llm`). |
| `ops/docker-compose.online.yml` | Overlay: unsets `PROVENANCE_OFFLINE` (real fastembed + reranker), points the LLM at the **host** Ollama via `host.docker.internal`, adds `extra_hosts: host-gateway`. |
| `ops/docker-compose.gpu.yml` | Overlay: grants the GPU (`deploy.resources.reservations.devices`) to `model`, `query-agent`, `parse`, and sets `PROVENANCE_ONNX_CUDA=1` so the ONNX paths request `CUDAExecutionProvider`. |

### Models used online

| Role | Model | Runs in | Backend | Device |
|---|---|---|---|---|
| Embeddings | `BAAI/bge-small-en-v1.5` | Model service | fastembed (ONNX) | GPU |
| Reranker (cross-encoder) | `BAAI/bge-reranker-v2-m3` | Model service | baked ONNX + `tokenizers` | GPU |
| Parse / OCR | Docling + RapidOCR (PaddleOCR ONNX) | Parse service | onnxruntime | GPU-capable (granted GPU access); Docling's layout/table models are torch, CPU unless `PARSE_USE_GPU` |
| LLM tiers | `qwen3.6:27b` (high), `qwen3.5:9b` (low) | **host Ollama** (OpenAI-compatible `/v1`) | Ollama | host GPU |
| Eval judge (optional) | Claude (`anthropic:…`) | eval only | Anthropic API | — |

### The image (`Dockerfile`)

A **multi-stage** build:

1. **`reranker-export` stage** (`python:3.12-slim`, CPU, discarded) — installs `optimum-onnx` +
   `transformers` + CPU `torch`, runs `optimum-cli export onnx` to convert
   `BAAI/bge-reranker-v2-m3` (which no fastembed release ships) to ONNX. It's independent of app
   code, so editing `services/` doesn't re-trigger the export.
2. **Runtime stage** (`nvidia/cuda:13.0.3-cudnn-runtime-ubuntu24.04`) — installs the three
   workspace packages editable, then **swaps** the CPU `onnxruntime` (pulled by fastembed/rapidocr)
   for **`onnxruntime-gpu`** so every ONNX model can use CUDA. Finally it `COPY`s the exported
   reranker to `/opt/models/bge-reranker-v2-m3`.

The onnxruntime-gpu wheel is **aarch64-only** (NVIDIA's SBSA/cu130 index; the reference machine
is the DGX Spark — GB10, aarch64, CUDA 13). The swap is therefore **guarded by `TARGETARCH`**:
arm64 installs the CUDA build; other arches (e.g. an x86 CI `docker build`) keep the CPU
onnxruntime and every ONNX model runs on CPU — the image still builds. Override with
`--build-arg ONNXRUNTIME_GPU=1|0`.

### Notable runtime env vars

| Var | Default | Effect |
|---|---|---|
| `PROVENANCE_OFFLINE` | `1` (base) | On ⇒ deterministic embedder + lexical reranker (no models). Unset ⇒ real models. |
| `PROVENANCE_ONNX_CUDA` | unset | On ⇒ embedder/reranker request `["CUDAExecutionProvider","CPUExecutionProvider"]`. |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | fastembed embedding model. |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | Reranker model; a basename match maps to the baked ONNX dir. |
| `RERANKER_ONNX_ROOT` / `RERANKER_ONNX_DIR` | `/opt/models` | Where baked reranker ONNX lives / explicit override. |
| `LLM_LOCAL_BASE_URL` | Ollama `/v1` | OpenAI-compatible local LLM endpoint. |
| `LLM_TIER_HIGH` / `LLM_TIER_LOW` | `local:qwen3.6:27b` / `local:qwen3.5:9b` | Tier aliases. |
| `LLM_<TASK>` | see §7 | Per-task routing (`extraction`,`detection`,`planner`,`synthesizer`,`critic`,`eval_judge`). |
| `LLM_REASONING_EFFORT` | `none` | Sent to the LLM; `none` disables hidden reasoning traces (else reasoning models return empty content). |
| `LLM_MAX_TOKENS` | `2048` | Max completion tokens for the local LLM. |
| `SERVICE_CALL_TIMEOUT_S` | `180` | Inter-service HTTP timeout (the agentic `/answer` path + cold model loads exceed the old 10s). |
| `CORS_ALLOW_ORIGINS` | `http://localhost:3000` | Gateway CORS origins (the browser UI is cross-origin). |
| `VECTOR_BACKEND` | `faiss` | `faiss` \| `qdrant` \| `pgvector` \| `opensearch`\* \| `weaviate`\* (\*stubs). |
| `PARSE_ENGINE` | `auto` | `auto` \| `docling` \| `pdfplumber`. |
| `MAX_ITERATIONS` | `3` | Hard bound on the Planner→Critic loop (R32). |

---

## 4. The data model — `packages/contracts`

Transport-neutral **Pydantic v1-style** models shared by every service (the single source of
truth, N9). Nothing here imports a service; services import these.

### `domain.py` — the Knowledge sub-domain
- **`ProcessingTier`** (`QUICK`=vector only, `FULL`=vector+graph) — capability chosen per ingest (R13).
- **`DocumentStatus`** — saga lifecycle: `QUEUED → PARSING → DETECTING → AWAITING_CONFIRM → EXTRACTING → WRITING → DONE|FAILED` (R5/R54).
- **`ParseMethod`** (`TEXT_LAYER`|`OCR`) — per-page provenance (R63).
- **`ElementType`** (`TEXT`|`HEADING`|`TABLE`|`FIGURE`) — typed parse element (R60).
- **`BBox`** — `page,x0,y0,x1,y1`; anchors a chunk to its source for citation highlight (R6/R36).
- **`KnowledgeBase`** — `id,name,domain_id,created_at`; domain pinned on creation (R2).
- **`Document`** — source + full processing provenance: `content_hash` (idempotency N5),
  `tier`, `status`, `detected_domain`, `detection_confidence`, `schema_version`,
  `schema_stale` (R70), `parse_method`, `ocr_engine`, `trace_id` (R56), `metadata`.
- **`Chunk`** — retrievable unit: `id,document_id,kb_id,text,page,bbox,reading_order,element_type` (R6/R60/R68).
- **`Entity`** — typed, KB-scoped graph node: `id,kb_id,type,canonical_name` (R22).
- **`Relation`** — typed edge `subject_id -[predicate]-> object_id` with `properties`.

### `messages.py` — the Interaction sub-domain (agent contracts, R34)
- **`SubqueryType`** (`FACTUAL`|`RELATIONAL`|`COMPARATIVE`) — drives routing (R29).
- **`Subquery`** (`text,type`), **`Plan`** (`kb_scope, subqueries, synthesis_strategy`) — Planner output.
- **`ScoredChunk`** (`chunk_id,text,page,bbox,score`) — a retrieved, scored chunk.
- **`EvidenceSet`** (`subquery, chunks, entity_ids, graph_expanded`) — Retriever output for one subquery (R30).
- **`Citation`** (`chunk_id,page,bbox`), **`Claim`** (`text,citations,grounded`) — atomic verifiable assertion (R65).
- **`Answer`** (`text, claims, refused, refusal_reason`) — Synthesizer output (R33/R65).
- **`CriticStatus`** (`OK`|`REVISE`), **`Verdict`** (`status, ungrounded_claims`) — Critic gate (R31/R32).

### `parse.py` — Parse→Ingestion boundary
- **`ParsedElement`** (`element_type,text,page,bbox,reading_order`) and **`ParseResult`**
  (`elements,pages,parse_method,page_methods,engine,engine_version`).

### `extraction.py` — Extraction→Ingestion boundary (pre-resolution candidates, R16)
- **`EntityCandidate`** (`type,canonical_name`), **`RelationCandidate`** (`subject,predicate,object,properties`),
  **`ExtractionResult`** (`domain_id,schema_version,entities,relations`). Extraction proposes by
  canonical name; the resolver assigns ids later.

### `ports.py` — the `VectorStorePort` (R20/R21)
- **`VectorRecord`** (`chunk_id,embedding,text,metadata`) — `text` carried for BM25 hybrid (R24).
- **`QueryHit`** (`chunk_id,score,text,metadata`).
- **`VectorStorePort`** (`Protocol`, `@runtime_checkable`) — `upsert / query / hybrid_query`,
  all `namespace`-scoped (namespace == `kb_id`, R4). This *is* the Vector service's API and the
  contract every adapter implements.

### `registry.py` — domains are data, not code (R15/R49)
- **`DomainTier`** (`BUILT`|`REGISTRY_READY`|`ROADMAP`), **`DomainSpec`**
  (`id,name,description,tier,entity_types,relation_types`).
- **`REGISTRY`** — the catalog: `sec_financial`, `research_papers`, `legal_contracts`,
  `technical_software`, `generic` (BUILT); `biomedical_clinical`, `regulatory_standards`,
  `patents` (REGISTRY_READY). `description` is what the detector matches against (R8).
  Adding/promoting a domain is a registry edit only (R48/R50). **`GENERIC_FALLBACK_ID = "generic"`**.

---

## 5. Shared framework — `packages/service`

Every service is built on this so shells are genuinely uniform.

### `settings.py`
- **`ServiceSettings`** (`pydantic-settings`, `env_prefix=""`) — `service_name`,
  `otel_exporter_otlp_endpoint`, `otel_service_namespace`, `nats_url`. Env-driven.

### `app.py`
- **`create_app(service_name, *, settings, readiness, on_startup, on_shutdown)`** — the FastAPI
  factory. Wires an async `lifespan` (startup/shutdown hooks), OTel via `setup_telemetry`, and two
  ops endpoints: **`GET /health`** (liveness, R69) and **`GET /ready`** (readiness → 200/503, degrades
  gracefully N6).
- **`traced_client(timeout=10.0)`** — an `httpx.AsyncClient` (globally instrumented so calls
  propagate trace context). *Note:* inter-service calls override this timeout via
  `SERVICE_CALL_TIMEOUT_S` in `clients.py` (default 180s).

### `telemetry.py`
- **`setup_telemetry(app, settings)`** — idempotent; builds a `TracerProvider`, attaches an OTLP
  gRPC exporter when configured, and instruments **FastAPI** (inbound) + **httpx** (outbound) so a
  single trace spans HTTP hops (R56).
- **`tracer(name="provenance")`** — get a tracer.

### `nats_client.py`
- **`NatsBus`** — thin NATS wrapper that carries the W3C trace context across the async boundary:
  **`connect/close/connected`**, **`publish(subject,payload)`** (injects trace context into headers,
  wraps in a PRODUCER span), **`subscribe(subject,handler,queue)`** (extracts context, attaches it,
  wraps the handler in a CONSUMER span). This is what keeps the ingestion trace unbroken across the
  queue (R54/R56).

### `llm.py` — multi-provider LLM routing (A2) — see §7.

---

## 6. The services

### 6.1 Gateway / BFF — `gateway.py` (+ `catalog.py`, `clients.py`)

The REST/SSE edge and the ingestion-saga entry point (R51/R53/R54). Owns the **Catalog**.

**`gateway.py`**
- `POST /kb` → **`create_kb`** — mint `kb_<uuid8>`, persist to Catalog.
- `POST /kb/{kb_id}/documents` → **`upload_document`** — accept base64 PDF (`content_b64`) or plain
  `content`; compute `content_hash` (idempotency N5); create a `queued` Document; publish an
  `ingest.jobs` NATS message; return **202** immediately (async saga).
- `GET /documents/{doc_id}` → **`get_document`** (200/404).
- `GET /kb/{kb_id}/stats` → **`kb_stats`** — proxied to Graph `/stats/{kb_id}`.
- `POST /query` → **`query`** — proxy to Query/Agent `/answer`; returns `{query, answer}`.
- `POST /query/stream` → **`query_stream`** — **SSE** (R35): emits `status` (retrieving →
  synthesizing) then streams `token`s, then a final `done` with `{answer, evidence}`.
- **`_on_status`** — subscribed to `ingest.status`; writes Document status transitions to the Catalog.
- **CORS** — `CORSMiddleware` added post-`create_app` (browser UI is cross-origin), origins from
  `CORS_ALLOW_ORIGINS`.

**`catalog.py`** — Postgres-backed KB/Document/Chunk store (owned only by Gateway, R52). Degrades
gracefully if the DB is briefly unavailable (N6):
- **`_dsn()`** — build the DSN from `POSTGRES_*` env.
- **`Catalog._ensure()`** — lazy (re)connect; if the gateway boots before Postgres, the pool is
  established on the first call that needs it (self-healing, avoids a permanent dead pool).
- **`connect / close / ready`**, **`create_kb`**, **`create_document`** (`ON CONFLICT (kb_id,content_hash) DO NOTHING`),
  **`update_status`**, **`get_document`**.

**`clients.py`** — service-to-service HTTP helpers. `SERVICE_URLS` maps logical names to base URLs
(overridable by `*_URL` env). **`call(service,path,payload)`** / **`call_get(service,path)`** POST/GET
JSON with trace propagation and a configurable timeout (`SERVICE_CALL_TIMEOUT_S`, default 180s —
raised from 10s because the agentic query + cold model loads legitimately take longer).

### 6.2 Ingestion — `ingestion.py` (+ `saga.py`)

The async **saga orchestrator** (R54). Subscribes to `ingest.jobs`; drives the pipeline; on failure
compensates in reverse; publishes status to `ingest.status`.

**`ingestion.py`** — each step is a coroutine over a shared `Ctx` dict:
- **`_parse_step`** → Parse `/parse` → `ParsedElement`s.
- **`_chunk_step`** → `chunk_elements` (structure-aware).
- **`_detect_step`** → Extraction `/detect` on a text sample → `domain`.
- **`_extract_step`** → Extraction `/extract` → entity/relation candidates.
- **`_graph_step`** → Graph `/write` (resolve + typed nodes/edges + provenance).
- **`_embed_step`** → Model `/embed` → embeddings.
- **`_vector_step`** → Vector `/upsert` (records carry `document_id`, `page`, `bbox` for citation).
- **`_build_saga()`** wires these as `Step`s (graph + vector have compensations).
- **`_run_saga(data,headers)`** — stamps `trace_id`, publishes `parsing`, runs the saga, then
  publishes `done` or `failed`.

**`saga.py`** — the reusable engine (not ingestion-specific):
- **`Ctx`**, **`Step(name,run,compensate)`**, **`SagaStatus`** (`DONE|FAILED|PAUSED`), **`SagaOutcome`**.
- **`SagaPause`** — a step raises it to **park** the saga (detect-but-confirm, R9/R55) *without*
  compensating.
- **`Saga.run(ctx)`** — run steps in order; on `SagaPause` return `PAUSED`; on any other exception,
  compensate completed steps in reverse (best-effort) and return `FAILED` with `failed_step`+`error`;
  else `DONE`. Never half-ingests.

### 6.3 Parse — `parse.py` (+ `parse_engine.py`, `docling_parser.py`, `ocr_engine.py`, `chunker.py`)

Layout-aware parsing → typed elements with `page + bbox + reading order` (R60–R64).

**`parse.py`**
- **`parse_document(content)`** — routes by `PARSE_ENGINE`: `auto` uses `needs_deep_parse` to pick
  `docling` (scanned/table-heavy) vs `pdfplumber` (clean prose); `docling` always deep (falls back to
  pdfplumber if Docling is unavailable); `pdfplumber` always light.
- `POST /parse` → **`parse`** — decode base64 → `parse_document` → `ParseResult`.

**`parse_engine.py`** — the lightweight, digital-first backend:
- **`needs_deep_parse(content)`** — cheap probe (no rendering): image-only page or tables ⇒ deep.
- **`parse_pdf_bytes(content, enable_ocr=True)`** — pdfplumber extracts **tables first** (kept whole,
  R62/R68) then text lines outside table bboxes; image-only pages fall back to OCR
  (`ocr_engine`); everything is sorted into reading order and each page's `ParseMethod` recorded.
- **`_center_in`** — helper: is a line's vertical center inside a table's span.

**`docling_parser.py`** — the richer document-understanding backend:
- **`_converter()`** — build a Docling `DocumentConverter` honoring `PARSE_USE_GPU`
  (`AcceleratorDevice.CUDA` vs `AUTO`); falls back to defaults on older Docling.
- **`parse_pdf_bytes_docling(content)`** — run Docling (layout + TableFormer + reading order +
  RapidOCR), map `TableItem`/`TextItem` (with `prov` geometry) onto `ParsedElement`s (tables →
  markdown; headings via label). *Docling's layout/table models are torch (CPU in the image); its
  OCR is ONNX.*
- **`_bbox(prov_item,page_index)`** — Docling bbox → contract `BBox`.

**`ocr_engine.py`** — OCR fallback that preserves geometry (so citations work on scans):
- **`OcrEngine._engine()`** — lazily build `RapidOCR` (ONNX PaddleOCR, Apache-2.0, CPU/GPU).
- **`OcrEngine.ocr_pdf_page(content,page_index)`** — render the page with pypdfium2 at 2×, OCR it,
  and return `(text, BBox)` in PDF coordinates (scaled back).
- **`get_ocr()`** — process-wide singleton.

**`chunker.py`** — structure-aware chunking (R68):
- **`chunk_elements(elements, *, document_id, kb_id, target_chars=1000, overlap_chars=150)`** — pack
  prose to ~`target_chars` with overlap; **tables become one chunk each** (never split mid-row);
  page boundaries close a chunk (never merge across pages); each chunk carries the **union bbox** of
  its source elements.
- **`_union_bbox(elements)`** — bounding box union.

### 6.4 Extraction — `extraction.py` (+ `detection.py`, `extraction_engine.py`)

Domain detection + schema-driven extraction (R8/R16). Owns the domain registry.

**`extraction.py`**
- `GET /domains` → **`domains`** — registry keys.
- `POST /detect` → **`detect_domain`** — heuristic (or LLM) detection + `needs_confirmation`.
- `POST /extract` → **`extract_entities`** — resolves the per-task LLM (`get_llm("extraction")`);
  with an LLM it does schema-constrained extraction, without one it's heuristic; result validated
  against the domain schema.

**`detection.py`** — runnable heuristic detector (R8) + detect-but-confirm (R9/R55):
- **`_signals(spec)`** — a domain's signal vocabulary (entity/relation type words + description words,
  minus non-discriminating stopwords).
- **`detect(text, registry=None)`** — score the sample against each non-generic domain by signal
  overlap; below `MIN_SIGNAL_HITS` ⇒ `generic`; else `{domain, confidence, rationale, low_confidence}`.
- **`should_pause_for_confirmation(d, threshold=0.55)`** — pause the saga when confidence is low.

**`extraction_engine.py`** — the extraction core (LLM-injectable):
- **`heuristic_generic(text)`** — no-LLM extraction for the generic domain (proper-noun phrases).
- **`validate_against_schema(entities, relations, spec)`** — **repair-by-dropping** (R16): drop
  off-schema entity types and off-schema predicates so only ontology-clean candidates survive.
- **`extract(text, spec, llm=None)`** — LLM path parses `{entities,relations}` from the model; generic
  no-LLM path uses `heuristic_generic`; typed no-LLM path yields nothing (real path = LLM). Always
  validated against the schema.
- **`make_llm_extractor(client)`** — bridge an `LLMClient` to the extractor (prompts for JSON of the
  domain's allowed types; tolerant JSON slice; `{}` on failure).

### 6.5 Graph — `graph.py` (+ `graph_store.py`, `resolver.py`)

Kuzu labeled-property graph; **entity resolution lives here** (ADR-001).

**`graph.py`**
- **`_get_store()`** — lazy `GraphStore` singleton at `KUZU_DB_PATH`.
- `POST /write` → **`write`** — resolve candidates to stable ids (merge co-referents), upsert typed
  nodes, then write relations whose subject/object both resolved, each carrying
  `kb_id + document_id + trace_id` (R22/R56).
- `GET /stats/{kb_id}` → **`stats`** — `{entity_count}`.
- `POST /link` → **`link`** — query-time entity linking (R26): an entity links when *all* its
  normalized name tokens appear in the query.
- `POST /expand` → **`expand`** — 1-hop neighbors of an entity (additive graph lift, R25/R27).

**`graph_store.py`** — embedded Kuzu (no server, ADR-001):
- **`_init_schema()`** — `Entity(id PK, kb_id, type, canonical_name)` node table and
  `Rel(FROM Entity TO Entity, predicate, kb_id, document_id, trace_id)` rel table.
- **`upsert_entities(entities)`** — `MERGE` on stable id (re-ingest densifies, never duplicates).
- **`write_relation(subject_id, predicate, object_id, *, kb_id, document_id, trace_id)`** — `MATCH`+`MERGE` edge with provenance.
- **`entity_count(kb_id)`**, **`entities(kb_id)`** (all `(id,type,name)` — basis for linking),
  **`neighbors(entity_id)`** (distinct 1-hop ids — basis for expansion), **`close()`**.

**`resolver.py`** — v1 entity resolution (R18/R19):
- **`normalize_name(name)`** — lowercase, strip punctuation, drop leading "the" and trailing org
  suffixes (`inc/corp/ltd/…`).
- **`entity_id(kb_id, type_, normalized)`** — deterministic `ent_<sha1[:12]>`: the *same* real-world
  entity gets the *same* id across documents (automatic cross-document merge).
- **`EntityResolver.resolve(kb_id, candidates, known_ids=None)`** → `ResolutionResult`
  (`entities`, `name_to_id`, `created`, `merged`). Reused at query time for linking (R26).

### 6.6 Model — `model.py` (+ `embedder.py`, `reranker.py`)

Embeddings **and** the cross-encoder reranker — the only always-GPU service (N7). Both loaded once
at import.

**`model.py`**
- `POST /embed` → **`embed`** — `{model_id, dim, embeddings}`.
- `POST /rerank` → **`rerank`** — score `documents:[{id,text}]` against the query; return `{model_id, ranked}`.

**`embedder.py`**
- **`Embedder`** protocol (`model_id, dim, embed`).
- **`_onnx_providers()`** — returns `["CUDAExecutionProvider","CPUExecutionProvider"]` when
  `PROVENANCE_ONNX_CUDA` is set, else `None` (fastembed default = CPU). Shared by the reranker.
- **`DeterministicEmbedder`** — SHA256 hash-based, stable, offline, dim-correct, **not semantic**
  (hermetic suite + CI).
- **`FastEmbedEmbedder(model_name)`** — real fastembed ONNX model; passes CUDA providers when enabled.
- **`get_embedder()`** — `DeterministicEmbedder` when `PROVENANCE_OFFLINE`, else `FastEmbedEmbedder`
  (falls back to deterministic if the model can't load).

**`reranker.py`**
- **`Reranker`** protocol (`model_id, rerank`).
- **`LexicalReranker`** — token-overlap (Jaccard), offline, not semantic.
- **`CrossEncoderReranker(model_name)`** — fastembed's ONNX cross-encoder (e.g. bge-reranker-base,
  ms-marco-MiniLM); CUDA providers when enabled.
- **`OnnxCrossEncoderReranker(model_dir, model_id)`** — loads a **build-time ONNX export** (for models
  fastembed doesn't ship, e.g. `bge-reranker-v2-m3`) with `onnxruntime` + the `tokenizers` lib (no
  transformers/optimum at runtime); runs on `CUDAExecutionProvider` when enabled. `rerank` tokenizes
  `(query, doc)` pairs (the exported `tokenizer.json` post-processor builds the template), pads, and
  returns the model logits as scores.
- **`_baked_onnx_dir(model_id)`** — resolves `RERANKER_ONNX_DIR` or `<RERANKER_ONNX_ROOT>/<basename>`
  and returns it only if `model.onnx` exists there.
- **`get_reranker()`** — offline ⇒ `LexicalReranker`; a baked export for `RERANKER_MODEL` ⇒
  `OnnxCrossEncoderReranker`; else fastembed `CrossEncoderReranker`; else lexical.

### 6.7 Vector — `vector.py` (+ `vector_factory.py`, `faiss_store.py`, `qdrant_store.py`, `pgvector_store.py`, `vendor_stubs.py`)

The `VectorStorePort` as a network API (R20/R21); namespace == `kb_id`.

**`vector.py`**
- `POST /upsert` → **`upsert`**.
- `POST /query` → **`query`** — dense by default; **hybrid** (dense + BM25) when `text` is present (R24).

**`vector_factory.py`**
- **`get_vector_store(backend=None)`** — select by `VECTOR_BACKEND`: `faiss` | `qdrant` | `pgvector`
  | `opensearch`\* | `weaviate`\* (\* = stubs). One contract, many backends.

**`faiss_store.py`** — in-memory embedded backend (default):
- **`_Namespace`** — one `IndexFlatIP` (inner product on L2-normalized = cosine) + parallel `ids/meta/texts`,
  with a lazily-(re)built `BM25Okapi`.
- **`FaissVectorStore.upsert`** — normalize + add; track ids/meta/text; mark BM25 dirty.
- **`query`** — dense cosine top-k with metadata filtering.
- **`hybrid_query`** — dense ranking + BM25 sparse ranking fused by **reciprocal rank fusion**
  (`RRF_K=60`) (R24).
- **`_tokenize`, `_passes`** — BM25 tokenizer, metadata filter predicate.

**`qdrant_store.py`** — dedicated-server backend (collection per kb_id; `:memory:` for tests; dense
cosine; hybrid falls back to dense v1). **`pgvector_store.py`** — in-database backend (vectors in
Postgres, `<=>` cosine; dense; hybrid falls back to dense v1). **`vendor_stubs.py`** —
`OpenSearchVectorStore` / `WeaviateVectorStore` satisfy the Port but raise `NotImplementedError`
(prove the Port is vendor-agnostic; mark where those adapters slot in).

### 6.8 Query / Agent — `query_agent.py` (+ `retrieval.py`, `crew.py`)

The only service that fans out on the query path (R53): retrieval core + the 4-agent crew.

**`query_agent.py`** — thin HTTP surface + the fan-out adapters:
- **`_embed`** → Model `/embed`; **`_hybrid`** → Vector `/query`; **`_rerank`** → Model `/rerank`
  (reorders hits by returned rank); **`_link`** → Graph `/link`; **`_expand`** → Graph `/expand`.
- **`_deps()`** — bundle those into a `RetrievalDeps`.
- `POST /retrieve` → **`retrieve_endpoint`** — one `EvidenceSet` for a query (R30).
- `POST /answer` → **`answer`** — run the crew: plan → retrieve per subquery → synthesize → critique →
  cited `Answer` (or refusal).

**`retrieval.py`** — the clean `query()` core, independent of agents (R24–R28):
- **`RetrievalDeps`** — injected `embed/hybrid/rerank/link/expand` (so the core is testable and reused
  in-process by the eval harness).
- **`retrieve(kb_id, query, deps, k=5)`** — **embed → hybrid (k×3) → rerank → top-k**, then additive
  graph lift (link → expand). **Vector is the floor; graph is the lift** (R25); no linked entities ⇒
  vector evidence stands (empty-expansion ladder, R27). Never graph-only.
- **`_to_chunk(hit)`** — `QueryHit` → `ScoredChunk` (rehydrates page + bbox from metadata for citations).

**`crew.py`** — Planner → Retriever → Critic → Synthesizer (R29–R33/R65). Each agent takes an optional
`LLMClient`; with none it runs deterministic heuristics (offline-safe), with one it uses the LLM.
- **`Planner.plan`** — `_llm_plan` (JSON decomposition) or `_heuristic_plan` (keyword typing:
  comparative → set_difference; relational vs factual). Output: a `Plan`.
- **`Synthesizer.synthesize`** — `_select_chunks` (executes the **set_difference** compare-op for
  comparative; else dedupe; a query-term **relevance gate** so irrelevant-but-retrieved chunks yield an
  honest refusal), builds chunk-derived `Claim`s **with citations**, and optionally rewrites the prose
  with `_llm_text` (evidence-only prompt). No chunks ⇒ **refuse** ("not supported by the corpus").
- **`Critic.verify`** — claim-by-claim groundedness (`_llm_grounded` YES/NO, or `_grounded` token-overlap
  ≥ `GROUNDING_THRESHOLD`); a refusal grounded in an *absence* is `OK` (R31). Any ungrounded claim ⇒
  `REVISE`.
- **`run_crew(query, kb_id, retrieve_fn, …, max_iterations=MAX_ITERATIONS)`** — plan → retrieve →
  **(synthesize → critique)\*** within a hard bound (R32). On `OK`, mark claims grounded and return.
  On exhaustion, **strict whole-answer refusal** — never release ungrounded content.

---

## 7. LLM routing — `packages/service/llm.py` (A2)

One abstraction, many providers; per-task routing so you define the models once and route each task
to a tier.

- **`LLMClient`** protocol (`complete(system, prompt) -> str`).
- **`MockLLMClient`** — canned responses (tests). **`AnthropicLLMClient`** — Claude via the `anthropic`
  SDK. **`OpenAICompatLLMClient(base_url, model, api_key=None)`** — covers **vLLM / Ollama / SGLang**
  via one OpenAI-compatible `/v1`; sends `max_tokens` (`LLM_MAX_TOKENS`) and **`reasoning_effort`**
  (`LLM_REASONING_EFFORT`, default `none`) — the latter is essential: reasoning models otherwise spend
  the whole budget in a hidden trace and return empty content.
- **`client_from_spec(spec)`** — resolve `"<provider>:<model>"`; a `high`/`low` alias expands to
  `LLM_TIER_HIGH`/`LLM_TIER_LOW`; `anthropic:` needs `ANTHROPIC_API_KEY`; local providers need
  `LLM_LOCAL_BASE_URL`; unresolved ⇒ `None` (heuristic fallback).
- **`get_llm(task)`** — read `LLM_<TASK>` (e.g. `LLM_SYNTHESIZER=high`) and build the client, else a
  recommended default; `None` ⇒ that agent runs heuristically.

Online defaults route detection/planning/extraction to the **low** tier (`qwen3.5:9b`) and
synthesis/critique to the **high** tier (`qwen3.6:27b`), all on the host Ollama; the eval judge stays
on Claude.

---

## 8. End-to-end flows

### Ingestion saga (async)
```
UI/POST /kb/{kb}/documents ─► Gateway: Document(queued) + publish ingest.jobs ─► 202
Ingestion worker (one trace, trace_id stamped):
  parse   → Parse /parse            (Docling/pdfplumber + OCR; typed elements + bbox)
  chunk   → chunk_elements          (prose packed; tables whole; union bbox)
  detect  → Extraction /detect      (heuristic/LLM domain; low confidence → could pause R9/R55)
  extract → Extraction /extract     (schema-constrained entity/relation candidates; repair-by-dropping)
  graph   → Graph /write            (resolve → stable ids → Kuzu nodes/edges + provenance)   [compensable]
  embed   → Model /embed            (bge-small on GPU)
  vector  → Vector /upsert          (records carry document_id + page + bbox)                 [compensable]
  → publish ingest.status=done  →  Gateway writes Document(done)
On any failure → compensate completed steps in reverse → Document(failed). No half-ingest.
```

### Query (synchronous, streamed)
```
UI/POST /query(/stream) ─► Gateway ─► Query/Agent /answer ─► run_crew:
  Planner    decompose + type subqueries (+ synthesis strategy)
  Retriever  per subquery: embed → Vector hybrid (dense+BM25 RRF) → Model rerank (bge-reranker-v2-m3, GPU)
             → top-k chunks;  Graph link → expand  (additive entity context; vector floor)
  Synthesizer  select chunks (set_difference for comparative; relevance gate) → cited Claims → (LLM prose)
  Critic       verify each claim grounded; refuse honestly on an absence; REVISE on any ungrounded
  loop (synthesize→critique) up to MAX_ITERATIONS → grounded Answer, or strict refusal
Gateway streams status → tokens → done{answer, evidence} over SSE.
```

---

## 9. Eval gate — `eval/`

Runs the **real** pipeline over a self-contained set and fails CI below §9.2 thresholds (R44). Uses
the deterministic embedder + lexical reranker + heuristic crew so it's hermetic; the LLM-judged RAGAS
metrics run on the Spark.

- **`harness.py`** — **`InProcessSystem`** wires the actual `chunker`, `FaissVectorStore`, Kuzu
  `GraphStore`, `EntityResolver`, `retrieve`, and `run_crew` in-process (no network). `ingest` and
  `answer` reproduce the real flow; `run_cases` drives the eval cases.
- **`metrics.py`** — **`THRESHOLDS`** (target/fail-below per §9.2) and the offline metrics:
  `numeric_exact_match` (R42), `rate`, `groundedness` (faithfulness proxy). `LLMJudge` /
  `ragas_faithfulness` are the Spark-only interface (return `None` offline).
- **`gate.py`** — **`compute_metrics`** (numeric exactness, honest-refusal, answer-rate, retrieval
  recall, groundedness, detection accuracy), **`evaluate`**, **`main`** (prints PASS/FAIL per metric;
  exit non-zero on any failure). Invoked in CI as `python -m provenance_eval.gate`.
- **`golden.py` / `benchmark*.py`** — golden-set seed/loader (R40) and the vector-backend benchmark
  harness (embedded vs server vs in-DB; see [`benchmark.md`](benchmark.md)).

---

## 10. Web UI — `web/` (Next.js, app router, TypeScript)

- **`lib/types.ts`** — TS mirrors of the answer/evidence contracts + `DOMAINS`, `ProcessingTier`.
- **`lib/api.ts`** — the gateway client (`NEXT_PUBLIC_GATEWAY_URL`, default `:8000`): `createKb`,
  `uploadDocument`, `getDocument`, `kbStats`, and **`streamQuery`** which consumes the `/query/stream`
  SSE (parses `status`/`token`/`done` frames). Because it fetches the gateway cross-origin, the gateway
  runs CORS.
- **`app/ingest/page.tsx`** — KB create (with domain), upload, Quick/Full tier, status polling.
- **`app/chat/page.tsx`** — KB scope, SSE streaming answer, honest-refusal display; plus
  **`components/CitationPanel.tsx`** (page + bbox highlight) and **`components/EntityGraph.tsx`** (live
  entity graph).

---

## 11. Cross-cutting concerns

- **Tracing = provenance (R56).** FastAPI + httpx are auto-instrumented; NATS propagation is explicit
  in `NatsBus`. The ingestion trace *is* the document's provenance chain (detected → parsed → extracted
  → embedded → stored), and `trace_id` is written onto the Document and every graph edge.
- **Licensing (R59).** `scripts/license_audit.py` fails CI on any SSPL/BSL/GPL dependency. Every
  datastore and model is permissive: Kuzu (MIT), FAISS (MIT), Qdrant (Apache), pgvector (PostgreSQL),
  fastembed/onnxruntime (Apache/MIT), bge-small & bge-reranker-v2-m3 (Apache/MIT), RapidOCR (Apache).
  *(Note: `jina-reranker-v2` is CC-BY-NC and would fail the audit — it is intentionally not used.)*
- **Graceful degradation (N6).** Missing DB, missing model, missing LLM endpoint, or offline mode all
  degrade to a working fallback (lazy reconnect, deterministic embedder, lexical reranker, heuristic
  agents) so tests and the eval gate always pass without external services.
- **CI.** `ruff` + `mypy --strict` (on `packages/contracts/src packages/service/src services/src`) +
  `pytest packages services eval` + the license audit + `PROVENANCE_OFFLINE=1 python -m provenance_eval.gate`.

---

## 12. File index

| Path | What it is |
|---|---|
| `packages/contracts/src/provenance_contracts/domain.py` | Knowledge sub-domain models (KB, Document, Chunk, Entity, Relation, BBox, enums) |
| `…/messages.py` | Interaction sub-domain (Plan, Subquery, EvidenceSet, Claim, Answer, Verdict) |
| `…/parse.py` · `…/extraction.py` | Parse and Extraction boundary contracts |
| `…/ports.py` | `VectorStorePort` + `VectorRecord`/`QueryHit` |
| `…/registry.py` | Domain registry (domains-as-data) |
| `packages/service/src/provenance_service/app.py` | `create_app`, `traced_client` |
| `…/telemetry.py` · `…/nats_client.py` · `…/settings.py` | OTel wiring · trace-propagating NATS bus · settings |
| `…/llm.py` | LLM clients + per-task router |
| `services/src/provenance_services/gateway.py` | REST/SSE edge, saga entry, CORS |
| `…/catalog.py` · `…/clients.py` | Postgres catalog (lazy reconnect) · inter-service HTTP (timeout) |
| `…/ingestion.py` · `…/saga.py` | Saga orchestrator · reusable saga engine + compensation |
| `…/parse.py` · `…/parse_engine.py` · `…/docling_parser.py` · `…/ocr_engine.py` · `…/chunker.py` | Parse service + backends + OCR + chunker |
| `…/extraction.py` · `…/detection.py` · `…/extraction_engine.py` | Extraction service + detector + engine |
| `…/graph.py` · `…/graph_store.py` · `…/resolver.py` | Graph service + Kuzu store + entity resolution |
| `…/model.py` · `…/embedder.py` · `…/reranker.py` | Model service + embeddings + reranker (incl. baked-ONNX v2-m3) |
| `…/vector.py` · `…/vector_factory.py` · `…/faiss_store.py` · `…/qdrant_store.py` · `…/pgvector_store.py` · `…/vendor_stubs.py` | Vector service + backend selection + adapters |
| `…/query_agent.py` · `…/retrieval.py` · `…/crew.py` | Query service + retrieval core + agent crew |
| `eval/src/provenance_eval/{gate,harness,metrics,golden,benchmark*}.py` | Eval gate, in-process harness, metrics, golden set, benchmark |
| `web/lib/{api,types}.ts` · `web/app/{ingest,chat}/page.tsx` · `web/components/*` | Frontend client, types, screens, citation panel + entity graph |
| `Dockerfile` · `ops/docker-compose*.yml` · `ops/sql/catalog_init.sql` | Multi-stage GPU image · base + online + gpu overlays · catalog schema |
| `scripts/{start,stop}.sh` · `scripts/license_audit.py` | Stack up/down · R59 license audit |
