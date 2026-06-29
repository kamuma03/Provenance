# Feature Plan: Provenance — Requirements & Success Specification

**Date**: 2026-06-28
**Project**: Provenance (greenfield)
**Status**: Planning — requirements consolidation

---

## 0. What this document is

A detailed requirements specification and definition-of-success for **Provenance**:
a provenance-aware RAG + Knowledge Graph system. Every functional requirement
carries a binary, testable acceptance criterion. Section 9 defines success at four
levels — per-requirement, system eval-gate, demo, and portfolio.

This is the consolidation of the design agreed in conversation. Where a detail was
not explicitly decided, it appears as a **stated assumption** (Section 10) or an
**open question** (Section 12), not a silent choice.

---

## 1. Overview

### Goal
Provenance lets a user build named knowledge bases from their own documents and
then chat with those documents, where **every answer traces back to a specific
source span** (page + bounding box). On ingestion, the system auto-detects the
document's domain, selects the matching extraction schema, and populates both a
vector store (for semantic recall) and a typed knowledge graph (for multi-hop
relational reasoning). On query, an agentic crew plans, retrieves, critiques for
groundedness, and synthesizes a cited answer — and **honestly refuses when the
corpus doesn't support a claim**.

The system is built to run **air-gapped on-premise** and, via the same ports, on
an **AWS slice** — making "the same system, on-prem or cloud" a single
configuration flag rather than a rewrite.

### Scope

**In scope (v1):**
- Two UI surfaces: (1) ingestion with domain auto-detection + capability ladder,
  (2) chat-with-documents.
- Knowledge Base as a named, domain-pinned collection.
- A tiered domain catalog (see **Appendix A**):
  - **Built (golden-set + eval-gated):** SEC Financial, Research Papers, Legal/Contracts, Technical/Software docs, Generic (fallback).
  - **Registry-ready (schema defined, detector-routable, not eval-gated):** Biomedical/Clinical, Regulatory/Standards, Patents.
  - **Roadmap (named, schema sketched, not built):** Government/Legislation, News/Journalism.
- Capability tiers (two): **Quick (vector only)** / **Full (vector + graph + fixed schema)**.
  ("Ontology-guided" collapsed into Full — the fixed domain schema *is* the ontology.)
- Dual-store ingestion (vector + Kuzu graph) with provenance metadata.
- Incremental add with **v1 entity resolution** (exact + normalized-string match).
- Retrieval core: hybrid (dense + sparse) → rerank → additive 1-hop graph expansion.
- Agentic crew: Planner → Retriever → Critic → Synthesizer (bounded loop).
- `VectorStorePort` with **FAISS + Qdrant + pgvector** adapters live (all open-source); OpenSearch/Weaviate stubbed.
- **All datastores open-source and permissively licensed** (Postgres, Qdrant, Kuzu, FAISS, NATS) — see **Appendix C**.
- Eval harness as a CI gate (RAGAS + hallucination + domain-detection accuracy).
- One AWS deployment path alongside the on-prem default.
- **Microservices architecture from P0** — 8 independently deployable services with
  database-per-service, an async message queue, a saga-orchestrated ingestion
  pipeline, and distributed tracing (see **§3.M** and **Appendix B / ADR-001**).
- Supporting infrastructure: message queue (NATS JetStream), Catalog store
  (Postgres), service-to-service contracts (gRPC or REST + OpenAPI), OpenTelemetry tracing.

**Out of scope (v1):**
- Splitting the AutoGen crew into per-agent services (it stays one Query/Agent service — see ADR-001).
- Service mesh (Istio/Linkerd), Kubernetes operators, or multi-region — single-cluster only.
- Authentication, user accounts, multi-tenant isolation beyond KB collections.
- KB management CRUD beyond create / list (no rename, no merge, no delete-and-restore).
- User-supplied or auto-induced ontologies (we use **fixed** per-domain schemas only).
- v2 entity resolution (embedding-similarity blocking + LLM adjudication).
- Deep per-vendor vector features (adapters are CRUD + query only).
- Multi-page / settings / auth screens in the UI (two screens, frozen).
- Real-time collaborative or streaming document ingestion.
- Numeric-reasoning beyond exact-span verification (no financial calculation engine).

---

## 2. Domain Model (authoritative)

Two sub-domains, integrated only at the query boundary.

**Knowledge sub-domain (ingestion):**
```
KnowledgeBase (id, name, domain_id, created_at)
  └─OWNS─► Document (id, kb_id, source, type, detected_domain,
                      detection_confidence, schema_version, metadata)
            └─CONTAINS─► Chunk (id, doc_id, text, embedding, page, bbox)
                          └─MENTIONS─► Entity (id, kb_id, type, canonical_name)
Entity ─RELATES_TO─► Entity        (typed edge in Kuzu LPG, edge props allowed)
Document ─PROVENANCE─► Entity        (every fact traces to a source)
```

**Interaction sub-domain (query):**
```
Query (text, intent, kb_scope[])
  └─DECOMPOSES_TO─► Subquery (type: factual | relational | comparative)
                     └─RESOLVES_TO─► EvidenceSet (chunks[], entities[], scores)
Answer (text) ─CITES─► Chunk        (carries page + bbox for highlight)
Critic ─VERIFIES─► Answer            (verdict gates release)
```

---

## 3. Functional Requirements

Each requirement is binary and testable. Grouped by area. IDs are stable.

### 3.A Knowledge Base / Collections

| # | Requirement | Acceptance criterion |
|---|---|---|
| R1 | The user can create a named KnowledgeBase. | Verified when: POST creates a KB with a unique id and the name is returned; a second create with a duplicate name is rejected or disambiguated. |
| R2 | A KnowledgeBase pins its domain on creation (from the first document's confirmed domain). | Verified when: after first ingest, `kb.domain_id` is set and immutable; a test asserts subsequent writes cannot change it. |
| R3 | The user can list all KnowledgeBases with their domain and document count. | Verified when: GET returns each KB's `{id, name, domain_id, doc_count}`. |
| R4 | Storage is partitioned per KB across both stores. | Verified when: a query scoped to KB-A never returns chunks or entities belonging to KB-B (vector namespace + graph `kb_id` filter both enforced in one test). |

### 3.B Ingestion — upload & chunking

| # | Requirement | Acceptance criterion |
|---|---|---|
| R5 | The user can upload a document (PDF primary; plain text / HTML accepted). | Verified when: a PDF upload returns a `document_id` and transitions through `queued → processing → done` states observable by the UI. |
| R6 | Chunks carry page number and bounding box for every chunk, derived from Parse-service geometry (text-layer **or** OCR) — including scanned pages. | Verified when: every Chunk from both a born-digital and a scanned PDF has non-null `page` and a 4-tuple `bbox`; asserted over both sample documents. |
| R7 | Ingestion reports progress to the UI and surfaces a graph preview on completion. | Verified when: the UI receives status events and, on `done`, a preview of extracted entities/edges is returned. |
| R67 | Uploads are validated at the Gateway before enqueue: allowed MIME types (PDF/text/HTML), a size cap, and **safe parsing** (no execution of embedded scripts; defended against malformed/zip-bomb/oversized-page PDFs). | Verified when: a disallowed type is rejected; an oversized file is rejected; a malformed/bomb PDF fails the parse safely (bounded time/memory) and marks the Document `failed` without crashing the Parse service. |
| R68 | Chunking is structure-aware with a **fixed, documented policy**: target chunk size + overlap for prose, and **tables chunked as coherent units** (a table — or a bounded row-group for large tables — stays in one chunk, never split mid-row). | Verified when: prose chunks honor the configured size/overlap; a known table is retrievable as one chunk (or contiguous row-groups) with cell structure intact; asserted over a sample table document. |

### 3.C Ingestion — domain detection (detect-but-confirm)

| # | Requirement | Acceptance criterion |
|---|---|---|
| R8 | The system auto-detects the document domain and returns `{domain, confidence, rationale}`. | Verified when: ingesting a known-SEC doc returns `domain = sec_financial` with confidence and a non-empty rationale string. |
| R9 | Detection is a **proposal**: the UI shows the detected domain and confidence, and the user can override before commit. | Verified when: the ingest flow exposes the proposed domain in a selectable control; an override changes the schema actually used (asserted by the recorded `schema_version`). |
| R10 | Below a confidence threshold, or when no domain matches, the system defaults to the **Generic** schema and flags it. | Verified when: a deliberately out-of-domain doc is extracted with the generic schema and the Document is marked `low_confidence = true`. |
| R11 | The detected domain, confidence, and schema version are recorded as provenance on the Document. | Verified when: `document.detected_domain`, `.detection_confidence`, `.schema_version` are persisted and returned by the document API. |
| R12 | Adding a document whose detected domain differs from the KB's pinned domain raises a warning (add-anyway / new-KB), never a silent mismatch. | Verified when: ingesting a Contracts-looking doc into a Financial KB returns a `domain_mismatch` warning that the user must resolve. |

### 3.D Ingestion — capability ladder

| # | Requirement | Acceptance criterion |
|---|---|---|
| R13 | The user selects one of **two** processing tiers per ingest: **Quick** (vector only) or **Full** (vector + graph + fixed domain schema). Parse/OCR (R60–R64) runs in **both** tiers (bbox is always required). | Verified when: choosing Quick populates the vector store and **not** the graph; Full populates both; both tiers produce page+bbox chunks; assertions on store contents confirm each tier. |
| R14 | The chat is honest about reduced capability for Quick-tier KBs. | Verified when: a relational query against a Quick-tier KB returns vector-grounded results plus an explicit "no relational evidence (vector-only KB)" note. |

### 3.E Domain registry & extraction

| # | Requirement | Acceptance criterion |
|---|---|---|
| R15 | Domains are defined in a registry as data: `{id, name, description, entity_types[], relation_types[], extraction_schema}`. | Verified when: a new domain can be added by a registry entry only (no code change), and it becomes selectable in detection — asserted by a test that registers a 4th domain. |
| R16 | Extraction conforms to the selected domain's typed schema (Pydantic-validated). | Verified when: extracted entities/relations validate against the domain schema; an extraction that violates the schema is rejected/repaired, never persisted raw. |
| R17 | v1 ships the **Built** domains (SEC Financial, Research Papers, Legal/Contracts, Technical/Software, Generic) with their full entity/relation types and golden-set coverage. | Verified when: each Built domain's registry entry contains its documented types (Appendix A) and has golden-set entries (§9.2). |
| R48 | v1 also ships **Registry-ready** domains (Biomedical/Clinical, Regulatory/Standards, Patents) as detector-routable schema entries, without golden-set/eval gating. | Verified when: each Registry-ready domain is selectable by the detector and validates extraction against its schema; absence of golden-set entries does not fail CI. |
| R49 | The detector can route to **any registered domain regardless of tier**, and the tier of a domain is metadata, not a code path. | Verified when: a document matching a Registry-ready domain is detected and extracted with that schema via the same code path as a Built domain. |
| R50 | Promoting a domain from Roadmap → Registry-ready → Built requires only adding a registry entry and (for Built) golden-set entries — no change to detection, extraction, or storage code. | Verified when: a test promotes a Roadmap domain by adding a registry entry and it becomes detectable, with no edits outside the registry and golden set. |
| R70 | When a domain's `schema_version` changes, documents extracted under an older version are **flagged stale** (not silently mixed); a documented **re-extraction** path rebuilds them. v1 policy: flag + manual re-extract trigger (full auto-migration deferred). | Verified when: bumping a domain schema marks prior documents `schema_stale=true`, the document API surfaces the flag, and a re-extract routine clears it under the new version. |

### 3.F Incremental add & entity resolution

| # | Requirement | Acceptance criterion |
|---|---|---|
| R18 | Adding a document to an existing KB merges co-referent entities rather than duplicating them (v1: exact + normalized-string match on `canonical_name` + `type`). | Verified when: ingesting two docs that both mention the same normalized company name yields **one** Entity node with edges from both documents. |
| R19 | The graph densifies across documents — cross-document relations are queryable. | Verified when: a relation asserted in doc A and an entity introduced in doc B participate in one multi-hop path returned by a graph query. |

### 3.G Storage ports & adapters

| # | Requirement | Acceptance criterion |
|---|---|---|
| R20 | A single `VectorStorePort` defines `upsert(ns, …)`, `query(ns, vec, k, filter)`, `hybrid_query(...)`; every method is namespace-scoped. | Verified when: the same test suite passes unchanged against two adapters by swapping a config flag only. |
| R21 | Three open-source adapters are live — **FAISS** (embedded), **Qdrant** (dedicated server), **pgvector** (in-Postgres); OpenSearch/Weaviate exist as stubs. | Verified when: FAISS, Qdrant, and pgvector pass the Port conformance suite by swapping a config flag only; stubs raise `NotImplemented` cleanly without breaking import. |
| R22 | The knowledge graph is a typed Kuzu LPG with a `kb_id` property on every node. | Verified when: nodes/edges are typed per schema and a `kb_id` filter isolates a KB's subgraph. |
| R23 | A benchmark harness produces a latency / recall / cost table across the three live adapters — comparing **embedded vs dedicated-server vs in-database** — over a fixed query set. | Verified when: running the benchmark emits a comparable table for FAISS, Qdrant, and pgvector on the same golden queries. |

### 3.H Retrieval core

| # | Requirement | Acceptance criterion |
|---|---|---|
| R24 | Retrieval is hybrid: dense + sparse (BM25), fused, then cross-encoder reranked. | Verified when: disabling rerank measurably changes ordering on a fixed query (rerank is provably in the path). |
| R25 | **Vector is the floor; graph is the lift.** Every subquery gets vector retrieval always; graph expansion is additive, never graph-only. | Verified when: a relational query whose entities are absent from the graph still returns vector-grounded evidence (no empty result). |
| R26 | Query→graph entity linking reuses the ingestion-side resolver (embed `canonical_name`s → ANN + type filter). | Verified when: the query "X's auditor" links "X" to the correct Company node, asserted against a seeded graph; a single resolver module is used by both paths. |
| R27 | Graph expansion failure degrades through a defined ladder (no-link → no-edge-of-type → no-path → entity's own chunks) rather than erroring. | Verified when: each rung is exercised by a crafted query and the system returns a graceful, vector-backed result at every rung. |
| R28 | Retrieval is exposed behind one clean `query()` API independent of the agent layer. | Verified when: `query()` can be called directly (without the crew) and returns an EvidenceSet. |
| R66 | The **same embedding model + version** is used at ingest and query; the model id+version is recorded per vector index, and a query embedded with a mismatched model is rejected (not silently mis-retrieved). A model change requires a recorded **re-embed** of the affected index. | Verified when: (a) a forced model-id mismatch between an index and the query embedder raises an explicit error; (b) the index metadata stores embedding model+version; (c) a re-embed routine rebuilds an index under a new model and updates the recorded version. |

### 3.I Agentic crew

| # | Requirement | Acceptance criterion |
|---|---|---|
| R29 | The Planner decomposes a Query into `Plan{subqueries[], synthesis_strategy}`, scopes the KB(s), and types each subquery (factual / relational / comparative). | Verified when: a comparative query yields ≥2 subqueries plus a declared compare operator in `synthesis_strategy`. |
| R30 | The Retriever resolves each subquery to an EvidenceSet via the retrieval core (no heavy LLM use). | Verified when: each subquery produces an EvidenceSet with chunks, entities, and scores. |
| R31 | The Critic returns `verdict{ok | revise, ungrounded_claims[]}`, **distinguishes "ungrounded claim" from "correctly grounded in an absence,"** and enforces **strict whole-answer groundedness**: an answer containing *any* ungrounded claim is never released as-is. | Verified when: (a) an answer asserting an unsupported fact yields `revise` with the claim listed and is **not** released; (b) a query about a fact genuinely absent from the corpus yields `ok` for the answer "the documents don't support this"; (c) a partially-grounded answer (3 of 4 claims) is **not** released as a trimmed partial — it is revised, never silently published with the bad claim dropped. |
| R32 | The Planner→Critic revision loop is bounded by a hard `MAX_ITERATIONS` constant, enforced and tested. On exhaustion with claims still ungrounded, the system **refuses the whole answer** ("cannot answer with grounded evidence") — it does **not** release a best-effort partial. | Verified when: a test forcing perpetual `revise` terminates at exactly `MAX_ITERATIONS` and returns a refusal, not a partial answer. |
| R33 | The Synthesizer composes the answer with inline citations (chunk → page + bbox) and executes the declared compare operator for comparative queries. | Verified when: a comparative query's answer reflects the set-difference (not the union), and every asserted sentence carries ≥1 citation. |
| R34 | All inter-agent messages use validated typed contracts (Pydantic). | Verified when: a malformed message between agents is rejected at the contract boundary, not deep in a handler. |
| R65 | A **claim** is defined as an atomic, verifiable assertion (one factual proposition). The Critic runs an explicit **claim-decomposition** of the draft answer into claims before verifying each against the EvidenceSet; strict refusal (R31/R32) operates at claim granularity. | Verified when: a multi-claim draft is decomposed into ≥N atomic claims (asserted against a known answer), each carries a grounded/ungrounded verdict, and the whole-answer release decision is a function of those per-claim verdicts. |

### 3.J Chat UI

| # | Requirement | Acceptance criterion |
|---|---|---|
| R35 | The chat streams the answer token-by-token over SSE. | Verified when: the client observes incremental tokens before the full answer completes. |
| R36 | A citation panel lets the user click a citation and highlights the exact source span (page + bbox). | Verified when: clicking a citation scrolls to the page and renders a highlight at the stored bbox. |
| R37 | A live force-graph shows the entities/edges used in the current answer. | Verified when: the graph view renders exactly the entities present in the answer's EvidenceSet and updates per answer. |
| R38 | The user selects which KB(s) the chat is scoped to. | Verified when: switching KB scope changes the retrievable corpus, asserted by a query that only one KB can answer. |
| R39 | When the corpus does not support a claim, the chat says so explicitly instead of fabricating. | Verified when: an out-of-corpus question yields an honest "not supported by the documents" answer with no fabricated citation. |

### 3.K Eval harness (CI gate)

| # | Requirement | Acceptance criterion |
|---|---|---|
| R40 | A golden set covers four cohorts: textual-factual, numeric-factual (exact span match), relational/multi-hop, and domain-detection (labeled docs). | Verified when: the golden set file contains all four cohorts with ≥ the minimum counts in Section 9.2. |
| R41 | RAGAS metrics (faithfulness, answer relevancy, context precision, context recall) run over the golden set. | Verified when: the harness emits all four metrics as numbers. |
| R42 | Numeric facts are verified by exact match against the cited span, **not** an LLM judge. | Verified when: a "$4.2B in 2022 vs 2021" trap is caught by span-exact comparison in a unit test. |
| R43 | Domain-detection accuracy is measured on held-out labeled docs. | Verified when: the harness reports detection accuracy as a percentage. |
| R44 | The eval harness runs as a CI gate with documented thresholds (Section 9.2), failing the build below threshold. | Verified when: an intentionally regressed change drops a metric below threshold and CI fails. |
| R45 | A thin smoke eval (faithfulness, ~10 pairs) runs from P2 onward; the full harness gates from P4. | Verified when: the smoke eval is wired before the full harness exists, and both are present by P4. |
| R71 | The eval gate measures **over-refusal**: an answer-rate cohort of known-**answerable** queries guards against strict refusal (R31/R32) suppressing valid answers. | Verified when: the harness reports answer-rate on the answerable cohort and CI fails if it drops below the §9.2 threshold (i.e. the system refuses too many answerable questions). |

### 3.L Deployment

| # | Requirement | Acceptance criterion |
|---|---|---|
| R46 | The full system runs air-gapped on-premise (local embeddings, reranker, graph, vector store; LLM endpoint configurable). | Verified when: with no outbound network except the configured LLM endpoint, ingestion + chat complete end-to-end. |
| R47 | One AWS deployment path runs the same system behind the same ports (managed vector + managed compute). | Verified when: flipping the deployment config routes the `VectorStorePort` and LLM to AWS services with no application-code change. |

### 3.M Service Architecture (microservices from P0)

The system is decomposed into the 8 services in **Appendix B**. These requirements
make the architecture testable.

| # | Requirement | Acceptance criterion |
|---|---|---|
| R51 | The system runs as 8 independently deployable services (Gateway, Ingestion, **Parse**, Extraction, Vector, Graph, Model, Query/Agent) plus a message queue and Catalog store. | Verified when: each service has its own container image and starts/stops independently; `docker-compose up` brings the full set online. |
| R52 | **Database-per-service**: no two services share a datastore. Cross-service data is joined by id over the wire. | Verified when: each stateful service owns exactly one store (Catalog→Postgres, Vector→indices, Graph→Kuzu, Extraction→registry); a test asserts no shared connection strings. |
| R53 | The query path is synchronous request/response; only the Query/Agent service fans out to Vector/Graph/Model. | Verified when: a chat request produces one fan-out from Query/Agent and no other service makes cross-service calls on the query path (asserted via trace). |
| R54 | The ingestion path is asynchronous and saga-orchestrated by the Ingestion worker, with compensating actions on failure. | Verified when: a forced failure at the vector-write step leaves the Document in `failed` (not `done`), with partial graph writes compensated — no half-ingested document persists (satisfies R5). |
| R55 | The detect-but-confirm gate (R9) is implemented as a saga pause: the ingestion job parks awaiting a confirm/override callback. | Verified when: a job halts after detection and resumes only on the confirm callback, with the chosen `schema_version` recorded. |
| R56 | Every request carries a W3C trace context propagated across all services (OpenTelemetry); the Document's provenance record is correlated to its ingestion `trace_id`. | Verified when: a single trace spans Gateway→Ingestion→Extraction→Graph/Model/Vector, and the Document row stores the correlating `trace_id`. |
| R57 | Inter-service contracts are versioned; a consumer pinned to vN keeps working when a provider ships vN+1 (additive change). | Verified when: a contract-compatibility test passes a vN consumer against a vN+1 provider. |
| R58 | The same service images deploy air-gapped (docker-compose) and on AWS (ECS/EKS) with only configuration changing — no application-code change. | Verified when: the AWS task-def swaps Vector→Qdrant-Cloud/OpenSearch, Model→SageMaker/Bedrock-embeddings, queue→SQS, Catalog→RDS via config only. |
| R59 | Every datastore and queue ships under a **permissive open-source license** (Apache 2.0 / MIT / BSD / PostgreSQL / MPL) — no SSPL, BSL, RSAL, or GPL/AGPL components in the default stack. | Verified when: a license-audit check (CI) over the dependency manifest passes against the Appendix C allowlist and fails if a non-permissive datastore is introduced. |
| R69 | Every service exposes **health and readiness** endpoints; the system degrades gracefully (N6) when a dependency is unready. | Verified when: each service answers a liveness/readiness probe; with Model unready, dependent calls return a clear error while unrelated endpoints (KB list, prior answers) still serve. |

### 3.N Document Parsing & OCR (Parse service)

The Parse service (8th service) performs layout-aware document understanding at
ingestion-saga step 1. These requirements make "better extraction via OCR" testable.

| # | Requirement | Acceptance criterion |
|---|---|---|
| R60 | The Parse service returns typed elements (text / table / figure / heading), each with `page`, `bbox`, and reading-order index. | Verified when: parsing a multi-column PDF yields elements in correct reading order, each with non-null page+bbox; a test asserts order on a known two-column page. |
| R61 | Parsing is **digital-first, OCR-fallback per page**: the embedded text layer is used when present; OCR runs only on scanned/image/garbled pages. | Verified when: a born-digital PDF is parsed without invoking OCR (asserted via the recorded method) and a scanned PDF triggers OCR. |
| R62 | **Table structure is recognized** and preserved as structured cells, not flattened to a text blob. | Verified when: a filing/paper table is parsed into rows×cols with cell bboxes; a test asserts cell count/shape against a known table. |
| R63 | The parse **method per page** (`text-layer` vs `ocr`), OCR **engine + version**, are recorded as provenance and correlated to the ingestion `trace_id`. | Verified when: each Chunk/Document carries its parse method + engine/version, retrievable via the document API. |
| R64 | The Parse service is **CPU-default** (preserves N7 — Model stays the only mandatory GPU service); its OCR/layout models are permissively licensed (Appendix C). | Verified when: the system parses end-to-end on a CPU-only host, and the license-audit (R59) covers the OCR dependencies. |

---

## 4. Non-Functional Requirements

| # | Requirement | Acceptance criterion |
|---|---|---|
| N1 | First answer token within ~3s; full grounded answer within ~10s for a typical single-hop query at demo scale. | Verified when: p50 over the golden query set meets these bounds on the **DGX Spark** (reference machine, A8). |
| N2 | Demo scale supported per KB: ≥ 100 documents / ≥ 50k chunks without retrieval degradation below eval thresholds. | Verified when: the eval gate still passes at that corpus size. |
| N3 | Single-user, local-first; no auth required to run. | Verified when: the app runs with no login and no user store. |
| N4 | Backend selection (vector adapter, LLM target, on-prem/AWS) is config-driven, no code edit. | Verified when: each is switchable via config/env and covered by a smoke test. |
| N5 | Ingestion is idempotent on re-upload of the same document into the same KB, keyed on a **content hash** (not filename). | Verified when: re-uploading byte-identical content does not duplicate chunks or entities; the same content under a different filename is still deduplicated; different content under the same filename is treated as new. |
| N6 | Each service is independently scalable and restartable without downing the system; a single service crash degrades gracefully, not totally. | Verified when: killing the Model service fails embedding/rerank-dependent calls with a clear error while KB listing and prior answers still serve. |
| N7 | The GPU-bound Model service is the only service requiring a GPU; all others run CPU-only. | Verified when: the compose file requests GPU for Model alone and the system starts on a CPU-only host with Model degraded. |
| N8 | Inter-service calls on the query path stay within the N1 latency budget (network hops are accounted for, not additive surprises). | Verified when: p50 end-to-end query latency including service hops meets N1 on the reference machine. |
| N9 | Service contracts are the single source of truth (generated clients/stubs), not hand-copied types. | Verified when: changing a contract regenerates clients and a drifted hand-written type fails CI. |

---

## 5. Alternative Approaches (key decisions, already taken in conversation)

These are recorded so the rationale is not lost; they are **decided**, not open.

| Decision | Chosen | Rejected alternative | Why |
|---|---|---|---|
| Ontology handling | Fixed per-domain schema + auto-detect | User-supplied / auto-induced ontology | Cheap (typed Pydantic), demoable; induction is a tar pit. |
| Vector vs graph at ingest | Two tiers: Quick (vector) / Full (vector+graph+schema) | Three tiers; or "vector OR graph" toggle | Fixed schema *is* the ontology, so "Ontology-guided" duplicated "Full" — collapsed to two. |
| Vector vs graph at query | Vector floor + additive graph lift | factual→vector / relational→graph XOR | Mis-routing must degrade to RAG, not to silence. |
| KB domain | Pinned on creation | Heterogeneous multi-domain KB | Typed Kuzu edges must compose; mixed schemas rot the graph. |
| Entity resolution v1 | Exact + normalized string | Embedding + LLM adjudication now | Scope dial; deterministic and demoable first. |
| Vector backends v1 | FAISS + Qdrant + pgvector live (all OSS), 2 stubbed | All deep; or include Pinecone | Open-source mandate; benchmark = embedded vs server vs in-DB (richer than vs a cloud API). |
| Datastore licensing | Permissive OSS only (Postgres/Qdrant/Kuzu/FAISS/NATS) | Pinecone (proprietary); Neo4j (GPL); Mongo/Redis (SSPL/RSAL) | Air-gap/on-prem legal review rejects source-available + copyleft (Appendix C). |
| Graph engine | **Kuzu** (MIT, embedded) | Neo4j Community (GPLv3) | MIT permissive + zero-infra embedded beats Neo4j's copyleft + server footprint. |
| Queue (§12.9 resolved) | **NATS JetStream** (Apache 2.0) | RabbitMQ (MPL) / Redis (RSAL — not OSS) | Light, fast, air-gap-friendly, permissive; Redis 7.4+ is no longer OSI-open. |
| Inter-service transport | **gRPC internal + REST/SSE at edge** | REST everywhere; gRPC everywhere | Typed/fast internal mesh; browser-debuggable edge without grpc-web. |
| Critic groundedness policy | **Strict whole-answer refusal** | Ok-with-caveat; revise-only | Provenance ethos: never publish an answer with any ungrounded claim (R31/R32). |
| Eval timing | Smoke at P2, full gate at P4 | Full harness only at P4 | P1–P3 need a regression net earlier. |
| Architecture style | **Full microservices from P0** (8 services) | Modular monolith, extract later | User decision; ports were already service-ready, so seams are clean (ADR-001). |
| Service granularity | 8 services by resource-profile + bounded-context | Per-noun nano-services / 1 service per agent | A service earns independence only via distinct resource profile or owned data — avoids distributed monolith. |
| OCR / parsing engine | **Docling (MIT) + PaddleOCR (Apache 2.0)** in a CPU-default Parse service | Surya/Marker (revenue-restricted), Nougat (NC), MinerU (AGPL), VLM-OCR | Must emit bboxes (citation-highlight) + be permissive (R59); VLM OCR loses geometry. |
| OCR strategy | Digital-first, OCR-fallback + table-structure | OCR every page; or text-only flatten | Speed + accuracy; structured tables/reading-order drive better extraction (the actual goal). |
| Crew placement | All 4 agents in one Query/Agent service | One service per agent | Agents share tight in-flight loop state; splitting = 4 hops per revision iteration. |
| Ingestion coordination | Orchestration-based saga (Ingestion worker) | Event choreography | Provenance needs explicit compensation; orchestration makes half-ingest impossible to hide. |

---

## 6. Impact Analysis (greenfield — proportionate)

| Dimension | Impact | Key concern |
|---|---|---|
| Architecture | High | **7 microservices from P0** (Appendix B), db-per-service, saga ingestion, hexagonal *inside* each service. Boundaries set in P0 or they leak. |
| UI/UX | Medium | Two frozen screens; force-graph + bbox highlight are the signature, also the scope-creep risk. |
| Frontend | Medium | Next.js streaming (SSE), citation panel, force-graph; one screen each, no more. |
| Backend | High | FastAPI + crew orchestration + retrieval core + ports; the integration surface. |
| Data | High | Vector namespaces + Kuzu typed LPG + entity resolution + provenance metadata. |
| Security | Low (v1) | No auth by design; file-upload input validation still required. |
| Safety (AI) | High | Critic groundedness, honest refusal, bounded loop, domain mis-detection — core to the value. |
| Performance | Medium | Rerank + graph expansion latency; N1 budget governs. |
| Testing | High | Port conformance suite, agent contract tests, eval gate — first-class, not afterthought. |
| Dependencies | Medium | LlamaIndex, AutoGen, Kuzu, RAGAS, FAISS/Qdrant/pgvector, Postgres, NATS — all permissive OSS; CI license-audit (R59) guards the on-prem claim. |
| DevOps | **High** | 7 containers + queue + Postgres; compose (air-gap) ↔ ECS/EKS (AWS); per-service CI; OpenTelemetry tracing; CI runs the eval gate. |
| Risk | High | Microservices integration + saga complexity up front; mitigated by P0 walking-skeleton (all services thin, one trace end-to-end before features). |

---

## 7. Implementation Phases (dependency-ordered, demo-back)

Each phase is independently demoable.

**P0 is now a *walking skeleton*: all 8 services exist as thin shells with real
contracts, wired through the queue + Catalog, emitting one end-to-end trace — before
any feature logic.** This front-loads the microservices integration risk so it never
surprises a later phase.

| Phase | Deliverable | Gates |
|---|---|---|
| P0 | **Walking skeleton**: 8 service shells + queue + Catalog(Postgres), domain model, `VectorStorePort` (= Vector svc contract), agent message contracts, domain registry shape, KB concept, versioned inter-service contracts, OpenTelemetry wired. A no-op upload flows Gateway→Ingestion→(stub Parse/Extraction/Graph/Model/Vector) and a no-op query flows Gateway→Query/Agent, each as one trace. `docker-compose up` works. | Contracts validate; one trace spans all services; no feature logic. |
| P1 | Fill the ingestion saga: **Parse service (Docling + PaddleOCR): layout, table-structure, digital-first/OCR-fallback, page/bbox**; Kuzu + FAISS writes; domain detection (detect-but-confirm as saga pause); Built schemas; v1 entity resolution; provenance metadata (incl. parse method) + `trace_id` correlation; compensation on failure. | A KB builds end-to-end via the saga; ~5 golden Q/A authored here. |
| P2 | Retrieval core behind `query()` — hybrid + rerank + additive graph expansion + entity linking + empty-expansion ladder. | Smoke eval (faithfulness) wired. |
| P3 | AutoGen crew on top of P2 — Planner/Retriever/Critic/Synthesizer, bounded loop, comparative compare-op. | Critic distinguishes ungrounded vs absent. |
| P4 | Full eval harness as CI gate — RAGAS + numeric span-check + detection accuracy. | Build fails below threshold. |
| P5 | Two-screen front-end against the P3 API — ingestion + chat with citations and force-graph. | Click-to-highlight works. |
| P6 | Remaining vector adapters + benchmark table; then the AWS slice. | Adapter swap by config; AWS path runs. |

---

## 8. Task Breakdown (P0–P1 detail; later phases summarized)

**P0 infrastructure tasks (microservices walking skeleton) — precede all feature tasks:**

| # | Task | Layer | Depends on | Complexity |
|---|---|---|---|---|
| S1 | Repo + per-service scaffold (8 services incl. Parse), shared contracts package, codegen for clients/stubs | DevOps | — | Medium |
| S2 | `docker-compose.yml`: 8 services + queue (NATS) + Postgres; GPU request on Model only (Parse CPU-default) | DevOps | S1 | Medium |
| S3 | Catalog service/store (Postgres): KB, Document, Chunk metadata + provenance + `trace_id` | Backend | S1 | Medium |
| S4 | Gateway/BFF: routing, SSE, ingestion-saga orchestrator skeleton | Backend | S1,S3 | Medium |
| S5 | Versioned inter-service contracts (gRPC/OpenAPI) + compatibility test | Backend | S1 | Medium |
| S6 | OpenTelemetry: W3C context propagation across all services; trace→provenance correlation | DevOps | S1 | Medium |
| S7 | Walking-skeleton e2e: no-op upload + no-op query each produce one full-span trace | Testing | S2–S6 | Medium |

**Feature tasks (each lands inside its owning service):**

| # | Task | Layer | Depends on | Complexity |
|---|---|---|---|---|
| 1 | Define domain-model types (KB, Document, Chunk, Entity, relations) | Backend | S1 | Low |
| 2 | `VectorStorePort` interface + conformance test suite | Backend | 1 | Medium |
| 3 | Agent message contracts (Plan, Subquery, EvidenceSet, Answer, Verdict) | Backend | 1 | Low |
| 4 | Domain registry shape + 3 domain entries (SEC, Research, Generic) | Backend | 1 | Medium |
| 5 | FAISS adapter implementing the Port | Backend | 2 | Medium |
| 6 | **Parse service**: Docling + PaddleOCR pipeline — layout, table-structure, digital-first/OCR-fallback, typed elements with page/bbox + reading order + parse-method provenance | Backend | S1,1 | Large |
| 6b | Structure-aware chunker consuming Parse elements (tables kept intact) | Backend | 6 | Medium |
| 7 | Domain detector (classify → confidence + rationale) | Backend | 4 | Medium |
| 8 | Schema-driven extraction (Pydantic) + repair-on-invalid | Backend | 4,6 | Medium |
| 9 | v1 entity resolver (exact + normalized) shared module | Backend | 8 | Medium |
| 10 | Kuzu writer (typed nodes/edges, kb_id) + provenance metadata | Backend | 8,9 | Medium |
| 11 | Author ~5 golden Q/A with source spans | Eval | 10 | Low |
| 12 | Retrieval core: hybrid + rerank | Backend | 5 | Large |
| 13 | Graph expansion + query→graph linking + empty-expansion ladder | Backend | 10,12 | Large |
| 14 | `query()` API | Backend | 12,13 | Low |
| 15 | Smoke eval (faithfulness, ~10 pairs) | Eval | 14 | Low |
| 16 | AutoGen crew (4 agents, bounded loop, compare-op) | Backend | 14 | Large |
| 17 | Full eval harness + CI gate | Eval/DevOps | 16 | Large |
| 18 | Ingestion UI (upload, detect-confirm, ladder, progress, preview) | Frontend | 10 | Medium |
| 19 | Chat UI (SSE stream, citation panel + bbox highlight, force-graph, KB select) | Frontend | 16 | Large |
| 20 | Qdrant + pgvector adapters + OpenSearch/Weaviate stubs + benchmark table | Backend | 5 | Medium |
| 21 | AWS deployment path behind config | DevOps | 14,16 | Large |

---

## 9. Definition of Success (the core of this document)

Success is defined at four levels. All four must hold for the project to be "done."

### 9.1 Per-requirement success
Every requirement R1–R71 and N1–N9 passes its acceptance criterion as an automated
test (or a documented manual check where automation is impractical, e.g. the bbox
highlight render). "Done" for a requirement = its criterion is green in CI.

### 9.2 System eval-gate success (the numbers CI enforces)

These thresholds gate the build from P4. Numbers are starting targets, tunable
once the golden set exists, but the **gate must exist and must fail below them**.

| Metric | Cohort | Target | CI fails below |
|---|---|---|---|
| Faithfulness (RAGAS) | textual-factual | ≥ 0.90 | 0.85 |
| Answer relevancy (RAGAS) | all | ≥ 0.85 | 0.80 |
| Context precision (RAGAS) | all | ≥ 0.80 | 0.75 |
| Context recall (RAGAS) | all | ≥ 0.80 | 0.75 |
| Numeric exactness (span match) | numeric-factual | = 1.00 | < 1.00 |
| Multi-hop answer correctness | relational | ≥ 0.80 | 0.70 |
| Domain-detection accuracy | detection set | ≥ 0.90 | 0.85 |
| Honest-refusal rate | out-of-corpus probes | ≥ 0.95 | 0.90 |
| Answer rate (over-refusal guard) | answerable cohort | ≥ 0.90 | 0.85 |

Golden-set minimum counts: textual-factual ≥ 20, numeric-factual ≥ 10,
relational/multi-hop ≥ 10, domain-detection ≥ 10 labeled docs (covering all four
real **Built** domains + ≥ 2 Registry-ready domains + ≥ 1 out-of-domain → Generic),
out-of-corpus probes ≥ 5, **answerable cohort ≥ 15** (known-answerable, incl. ≥ 5
multi-claim/comparative to guard against strict-refusal over-suppression). Registry-ready
domains contribute detection labels only; they are not required to meet the
RAGAS/multi-hop thresholds in v1.

### 9.3 Demo success (the moment an interviewer remembers)
A single live demo proves the system end-to-end:
1. Upload an SEC 10-K → system detects "SEC Financial" with confidence, user confirms.
2. Upload a second related filing → entities **merge**; the force-graph visibly densifies.
3. Ask a **comparative multi-hop** question ("risk factors cited in 2022 but not 2021").
4. Answer streams in, every claim **cited**; clicking a citation **highlights the exact span**.
5. The force-graph shows the **entities/edges used**.
6. Ask something **not in the documents** → system **honestly refuses** with no fake citation.
7. Flip a config flag → the **same query runs against a different vector backend**
   (FAISS → Qdrant → pgvector), proving the Port. (AWS path is a P6 add-on, not part of the core demo.)

If steps 1–7 run without hand-waving, the demo succeeds.

### 9.4 Portfolio / hireability success (why this project exists)
The repo surfaces, as real artifacts (not buzzwords):
- **LlamaIndex** retrieval core, **AutoGen** crew, **Kuzu** graph, and **FAISS + Qdrant
  + pgvector** behind one Port with a **published embedded-vs-server-vs-in-DB benchmark**.
- A **fully open-source, permissively-licensed stack** with a CI license-audit — the
  "I understand SSPL/BSL/GPL vs permissive, and my on-prem claim survives legal review" signal.
- An **eval harness wired as a CI gate** (RAGAS + hallucination + detection accuracy) —
  the "eval-literate, ships a regression suite" signal.
- A **two-screen demo** with citation highlight + live entity graph.
- "**Same system, air-gapped or on AWS**" as one config flag.
- Provenance as a first-class property: even *how a fact was extracted* (domain,
  confidence, schema version) is traceable.

---

## 10. Stated Assumptions (decided-by-default, flag if wrong)

- **A1** Input format priority: PDF (for page/bbox), then plain text/HTML. **OCR is in
  scope** via the Parse service (Docling + PaddleOCR) — scanned/image PDFs supported
  through digital-first/OCR-fallback (R60–R64). Handwriting and non-Latin scripts are
  best-effort, not a v1 guarantee.
- **A2** LLM: Claude (Opus/Sonnet) for detection, extraction, planning, critic, synthesis,
  via a configurable endpoint (local-compatible for air-gap).
- **A3** Embeddings + reranker: local open models (e.g. BGE/E5 family) so on-prem is truly
  air-gapped; swappable by config.
- **A4** Single concurrent user. A real message queue (NATS) exists for the ingestion
  saga, but is sized for one user's document throughput, not multi-tenant load.
- **A8** Reference machine = **DGX Spark** (air-gapped, GPU). All N1/N2/§9.2 latency
  and scale figures, and the vector benchmark, are measured here. Model + Parse use its GPU.
- **A7** Datastore stack (open-source, permissive): **Postgres** (Catalog),
  **Qdrant + FAISS + pgvector** (Vector adapters), **Kuzu** (Graph), **NATS** (queue).
  Locked per Appendix C / R59; swappable only for another permissive-licensed engine.
- **A5** "Cost" in the benchmark table is modeled/estimated for managed vendors, measured
  for local — not a billing integration.
- **A6** AWS slice targets one path (e.g. Bedrock or SageMaker + Lambda + API Gateway +
  OpenSearch or pgvector); exact services finalized in P6.

---

## 11. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Silent domain mis-detection corrupts extraction | Medium | High | Detect-but-confirm (R9) + generic fallback (R10) + provenance record (R11). |
| Graph expansion returns nothing → dead-end answers | Medium | High | Vector-floor/graph-lift (R25) + empty-expansion ladder (R27). |
| Critic loop never terminates | Medium | High | Hard `MAX_ITERATIONS` as constant + test (R32). |
| Scope creep (4 vendors, extra screens, auto-ontology) | High | Medium | Explicit out-of-scope (Section 1) + scope dials in decisions (Section 5). |
| Domain catalog over-build (gold-plating 8+ golden sets) | High | Medium | **Tiering** (Appendix A): only Built domains are eval-gated; Registry-ready are schema-only (R48); detector routes to all via one code path (R49). |
| Numeric hallucination passes eval | Medium | High | Span-exact numeric check, not LLM judge (R42). |
| Entity-resolution under-merge fragments the graph | Medium | Medium | v1 normalized match (R18); v2 deferred and named. |
| LlamaIndex/AutoGen abstractions fight control | Medium | Medium | Drop to low-level retriever/agent APIs; keep crew to 4 roles. |
| Integration complexity stalls delivery | Medium | High | Demoable-per-phase ordering (Section 7) — always something to show. |
| Distributed monolith (services that must deploy together / share data) | High | High | Db-per-service (R52) + versioned contracts (R57) + the two deliberate non-splits (ADR-001). |
| Microservices integration risk discovered late | Medium | High | P0 walking skeleton — all 8 services + one e2e trace before any feature logic. |
| OCR drops bboxes (breaks citation highlight) | Medium | High | Layout-OCR (Docling/Paddle) chosen for geometry over VLM; R60 asserts page+bbox on every element. |
| OCR GPU load contends with query-path rerank | Low | Medium | Parse is CPU-default + ingestion-only; never on query path (preserves N7/N8). |
| Saga leaves a document half-ingested | Medium | High | Orchestration-based saga with compensation (R54); status transitions asserted (R5). |
| Network hops blow the latency budget | Medium | Medium | Only Query/Agent fans out (R53); hops measured against N1 (N8). |

---

## 12. Resolved Decisions & Deferred Items

All planning questions are resolved. Two items are deliberately **deferred to P6**
(they don't block P0–P5).

| # | Question | Resolution |
|---|---|---|
| 1 | Reference machine | ✅ **DGX Spark** — air-gapped GPU box; N1/N2/§9.2 + benchmark figures measured here (Model + Parse get real GPU). |
| 2 | Reranker dependency | ✅ **Local cross-encoder** (e.g. `bge-reranker-v2-m3`) on the Model service — air-gap-clean, no LLM-as-reranker. |
| 3 | Numeric-factual cohort | ✅ **Exact-span match sufficient**; derived-arithmetic questions explicitly out-of-scope (flagged, not silently failed). |
| 4 | AWS exact services | ⏸ **Deferred to P6** — exact Bedrock/SageMaker, OpenSearch/pgvector-on-RDS chosen when the AWS phase starts. R58 stubbed until then. |
| 5 | Research-papers corpus | ✅ **arXiv bulk** (license-clean) + hand-pick ~10 for the golden set. |
| 6 | Critic on partial groundedness | ✅ **Strict whole-answer refusal** — any ungrounded claim ⇒ the whole answer is not released (revise → if unresolved at MAX_ITERATIONS, refuse). See R31/R33. |
| 7 | Domain tiers | ✅ **Confirmed** — Built: SEC · Research · Legal · Technical · Generic; Registry-ready: Biomedical · Regulatory · Patents. |
| 8 | Inter-service transport | ✅ **gRPC internal + REST at the Gateway edge** (R57/N9). |
| 9 | Message queue | ✅ **NATS JetStream** (Apache 2.0). |
| 10 | AWS orchestration | ⏸ **Deferred to P6** — ECS Fargate vs EKS decided at the AWS phase. |
| 11 | VLM-OCR | ✅ **v1 stays layout-OCR only** (bbox-safe); VLM (GOT-OCR2.0/Qwen2.5-VL) parked as a post-v1 upgrade. |
| 12 | Parse on GPU | ✅ **CPU-default**; promote to GPU only if OCR throughput bottlenecks at demo scale (N2). |

---

## Appendix A: Domain Catalog

Each domain is a registry entry: `{id, name, description, entity_types[],
relation_types[], extraction_schema}`. **Tier is metadata** — the detector routes to
every entry through one code path (R49). Closed, typed relation sets are what make
graph traversal compose; the Generic fallback's single open predicate is the visible
cost of falling back (it degrades to a non-traversable property graph).

### Tier 1 — Built (golden-set + eval-gated)

**`sec_financial` — SEC Financial**
```
Entities:  Company, Subsidiary, Person(officer/director), RiskFactor,
           FinancialMetric, FiscalPeriod, Auditor, LegalProceeding
Relations: OWNS_SUBSIDIARY, HAS_OFFICER, CITES_RISK (qualified by FiscalPeriod),
           REPORTED_METRIC (qualified by FiscalPeriod), AUDITED_BY, PARTY_TO
Data:      SEC EDGAR (10-K / 10-Q)            Demo: comparative multi-hop across periods
```

**`research_papers` — Research Papers**
```
Entities:  Paper, Author, Institution, Method, Dataset, Finding, Venue
Relations: AUTHORED_BY, AFFILIATED_WITH, USES_METHOD, EVALUATES_ON,
           REPORTS_FINDING, CITES (Paper→Paper), PUBLISHED_IN
Data:      arXiv                                Demo: citation force-graph, method→dataset hops
```

**`legal_contracts` — Legal / Contracts**  *(promoted to Built)*
```
Entities:  Party, Contract, Clause, Obligation, Term/Date, GoverningLaw,
           Signatory, Amendment
Relations: PARTY_TO, CONTAINS_CLAUSE, IMPOSES_OBLIGATION (Clause→Obligation, on Party),
           GOVERNED_BY, AMENDS (Amendment→Contract/Clause), EFFECTIVE_ON, SIGNED_BY
Data:      CUAD, EDGAR exhibits                 Demo: clause-level bbox highlight (best provenance story)
```

**`technical_software` — Technical / Software docs**  *(promoted to Built)*
```
Entities:  Component, API/Endpoint, Parameter, Dependency, Version, ErrorCode
Relations: DEPENDS_ON (Component→Dependency), EXPOSES (Component→API),
           DEPRECATES (Version/API→API), INTRODUCED_IN (API/Param→Version),
           RAISES (API→ErrorCode)
Data:      OpenAPI specs, library docs,         Demo: "what depends on X and was
           changelogs                                 deprecated in v3" — relation set
                                                      visibly distinct from finance/legal
```

**`generic` — Generic (fallback)**
```
Entities:  Person, Organization, Location, Date, Event, Concept
Relations: RELATES_TO (predicate as edge-property string), MENTIONS
Use:       low-confidence / out-of-domain      Note: non-traversable by type, by design
```

### Tier 2 — Registry-ready (schema defined, detector-routable, not eval-gated)

**`biomedical_clinical` — Biomedical / Clinical**
```
Entities:  Drug, Condition, Gene/Protein, ClinicalTrial, Dosage, AdverseEvent, Population
Relations: TREATS (Drug→Condition), INTERACTS_WITH (Drug→Drug),
           CONTRAINDICATED_FOR (Drug→Condition/Population), TARGETS (Drug→Gene),
           CAUSES_AE (Drug→AdverseEvent), STUDIED_IN (→ClinicalTrial)
Data:      PubMed abstracts, FDA labels         Caveat: golden set needs domain expertise
```

**`regulatory_standards` — Regulatory / Standards**
```
Entities:  Regulation, Article/Clause, Requirement, Authority, Definition, Penalty, Scope
Relations: CONTAINS_ARTICLE, REFERENCES (Clause→Clause), IMPOSES_REQUIREMENT,
           ISSUED_BY (→Authority), DEFINES (→Definition), PENALIZES, APPLIES_TO (→Scope)
Data:      GDPR, NIST, ISO                       Strength: clause-refs-clause = free graph edges
```

**`patents` — Patents**
```
Entities:  Patent, Inventor, Assignee, Claim, PriorArt, Classification(CPC/IPC)
Relations: INVENTED_BY, ASSIGNED_TO, HAS_CLAIM, CITES_PRIOR_ART (Patent→Patent/Ref),
           CLASSIFIED_AS
Data:      USPTO bulk                            Strength: prior-art citation graph
```

### Tier 3 — Roadmap (named, schema sketched, not built)

**`government_legislation`** — Bill, Legislator, Committee, Amendment, Vote, Statute ·
SPONSORED_BY, REFERRED_TO, AMENDS, VOTED_ON, ENACTS · data: congress.gov.

**`news_journalism`** — Person, Organization, Event, Location, Date, Outlet, Quote ·
PARTICIPATED_IN, LOCATED_IN, OCCURRED_ON, REPORTED_BY, QUOTED · overlaps Generic.

### Promotion path
Roadmap → Registry-ready: flesh the schema into a full registry entry (R48).
Registry-ready → Built: add golden-set entries and wire into the eval gate (R50).
Neither step touches detection, extraction, or storage code.

---

## Appendix B: Service Architecture (microservices from P0)

### B.1 Service map

```
                 ┌─────────────┐
                 │  Next.js UI │
                 └──────┬──────┘
                        │ HTTP + SSE
                 ┌──────▼───────────────┐     owns: KB / Document / Chunk
                 │  Gateway / BFF       │◄──► Catalog store (Postgres)
                 │  SSE · routing ·     │     + provenance + trace_id
                 │  ingestion-saga      │
                 │  orchestrator        │
                 └───┬──────────────┬───┘
        async (queue)│              │ sync (gRPC/REST)
            ┌────────▼───────┐  ┌───▼─────────────────────┐
            │ Ingestion svc  │  │  Query / Agent svc      │
            │ workers ·      │  │  retrieval core +       │
            │ saga driver +  │  │  AutoGen crew (4 roles, │
            │ compensation   │  │  bounded loop)          │
            └┬───┬───┬───┬───┘  └──┬───────┬──────┬───────┘
ingestion-only│   │   │   │ writes  │ fan-out (R53): Vector·Graph·Model
     ┌────────▼┐ ┌▼───▼┐ ┌▼──┐ ┌────▼──┐ ┌──▼───┐ ┌──────────┐
     │ Parse   │ │Extr-│ │Mod│ │Vector │ │Graph │ │  Claude  │
     │ OCR +   │ │action│ │el │ │ svc   │ │ svc  │ │ endpoint │
     │ layout+ │ │+regis│ │svc│ │Port + │ │Kuzu +│ │(external)│
     │ table   │ │(LLM) │ │emb│ │FAISS/ │ │entity│ └──────────┘
     │ (CPU,   │ └──────┘ │+rr│ │Qdrant/│ │resol.│
     │ Docling/│          │GPU│ │pgvec  │ │      │
     │ Paddle) │          └───┘ └───────┘ └──────┘
     └─────────┘   ▲
        step 1     │  message queue (NATS JetStream) ── status events ──┘
   (Model + Vector + Graph are shared: Ingestion writes, Query reads)
```

### B.2 Services — responsibility, data ownership, resource profile

| Service | Owns (data) | Responsibility | Profile | Earns independence by |
|---|---|---|---|---|
| **Gateway / BFF** | Catalog (Postgres): KB, Document, Chunk meta, provenance | SSE edge, routing, ingestion-saga orchestration | CPU, stateless edge | bounded context (edge + catalog) |
| **Ingestion** | — (drives others) | Async workers; structure-aware chunking; saga driver + compensation | CPU, bursty, queue-driven | distinct resource profile (bursty batch) |
| **Parse** | OCR/layout/table models | Layout-aware parsing: digital-first/OCR-fallback, table structure, reading order, page+bbox (Docling + PaddleOCR) | CPU-default, bursty, ingestion-only | bounded context (document understanding) + distinct load profile |
| **Extraction (+ registry)** | Domain registry (config) | Domain detection + schema-driven extraction | LLM-bound | bounded context (owns registry) |
| **Vector** | Vector indices (per-KB ns) | `VectorStorePort`: upsert/query/hybrid; FAISS/Qdrant/pgvector adapters | stateful, memory-heavy | owned data + the Port-as-API |
| **Graph** | Kuzu LPG (kb_id partition) | Typed nodes/edges, entity resolution, graph expansion | stateful, CPU | owned data |
| **Model** | model weights | Embeddings + cross-encoder reranker | **GPU**, steady | distinct resource profile (only GPU) |
| **Query / Agent** | — | Retrieval core (`query()`) + AutoGen crew | LLM + CPU, req/resp | bounded context (interaction) |

Two deliberate **non-splits** (ADR-001): the 4-agent crew stays inside Query/Agent;
entity resolution stays inside Graph. Eval is a CI **job**, not a live service.

### B.3 Communication

- **Query path — synchronous.** Gateway → Query/Agent → fan-out to Vector + Graph +
  Model (**gRPC** internal). Only Query/Agent fans out (R53). Tokens stream back via
  **SSE/REST** at the Gateway edge. This path carries the N1 budget — keep hops shallow (N8).
- **Ingestion path — asynchronous, saga-orchestrated.** Gateway enqueues a job and
  returns `202 + document_id`. The Ingestion worker is the orchestrator.

### B.4 Ingestion saga (orchestration + compensation)

```
Gateway: write Document(status=queued) to Catalog → enqueue → 202 + document_id
Ingestion worker (orchestrator):
   1. parse (layout/OCR/table) → Parse svc        (R60–R63) → structure-aware chunk
   2. detect domain            → Extraction       (R8)
   3. SAGA PAUSE: await confirm/override callback  (R9, R55)
   4. extract entities/relations → Extraction      (R16)
   5. resolve + write graph     → Graph            (R18)
   6. embed (Model) + write vectors → Vector
   7. Document(status=done) + provenance + trace_id → Catalog (R11, R56)
On any failure → COMPENSATE: roll back partial graph/vector writes,
   Document(status=failed). No half-ingested document persists. (R54)
Status events → queue → Gateway → SSE → UI progress (R7)
```

### B.5 Contracts & data ownership

- **Database-per-service (R52)** — single owner per store; services join by id over
  the wire, never by shared DB.
- **Versioned contracts (R57, N9)** — **gRPC protobufs internally, OpenAPI/REST at the
  Gateway edge**, in a shared contracts package; clients/stubs are generated, not
  hand-copied. The `VectorStorePort` is literally the Vector service's contract (strengthens R20).

### B.6 Provenance = distributed tracing

W3C trace context (OpenTelemetry) propagates through every hop (R56). The provenance
chain — *detected by Extraction vX (conf) → embedded by Model vY → stored in Vector
ns=Z → linked by Graph* — **is** the document's ingestion trace. Correlate `trace_id`
with the Document provenance record: one artifact serves both observability and product.

### B.7 Deployment topology (R58)

| Concern | On-prem / air-gapped | AWS |
|---|---|---|
| Orchestration | `docker-compose up` | ECS or EKS (same images) |
| Vector svc | FAISS / Qdrant / pgvector (local) | Qdrant Cloud / OpenSearch Service |
| Model svc | local BGE/E5 + cross-encoder (GPU) | SageMaker endpoint / Bedrock embeddings |
| Parse svc | Docling + PaddleOCR (CPU) | self-host on ECS/EKS — or swap to Textract / Document AI |
| Queue | NATS JetStream | SQS |
| Catalog | Postgres container | RDS |
| LLM | configured egress / local LLM | Bedrock / configured endpoint |
| Edge | Gateway container | API Gateway + ALB |

Only configuration changes between columns — no application code (R58).

---

## ADR-001: Full microservices from P0

**Status:** Accepted · **Date:** 2026-06-28

**Context.** Provenance is a single-user portfolio system. The hexagonal/ports design
already isolates storage and model concerns. The user explicitly chose full
microservices from P0 (not modular-monolith-then-extract).

**Decision.** Decompose into 8 independently deployable services (B.2), database-per-
service, async saga-orchestrated ingestion, synchronous fan-out-limited query path,
versioned contracts, OpenTelemetry tracing. Stand them up as a P0 *walking skeleton*
before feature logic.

**Why this granularity.** A service earns independence only via a **distinct resource
profile** (GPU Model svc vs CPU; bursty Ingestion vs steady) **or a distinct bounded
context with owned data** (Vector, Graph, Extraction-registry, Catalog). Anything else
stays merged — hence the crew is one service and entity resolution lives in Graph.

**Consequences.**
- (+) Independent scaling (esp. the single GPU service); clean air-gap ↔ AWS via the
  same images; strong distributed-systems signal; provenance == tracing.
- (−) Heavier P0 (queue, Postgres, 7 containers, contracts) before first feature demo;
  real risk of distributed-monolith and latency-from-hops.
- **Mitigations:** P0 walking skeleton front-loads integration risk; db-per-service +
  versioned contracts prevent the distributed monolith; only Query/Agent fans out.

**Rejected alternative.** Modular monolith with the same 7 modules behind ports,
extracted to services phase-by-phase (Model first). Lower upfront infra, same
boundaries — rejected per explicit user preference for full microservices from P0.

---

## Appendix C: Datastore Stack & License Policy

### C.1 The license filter (why source-available ≠ open-source)

For an air-gapped / on-prem product, the binding constraint is the **license class**,
not raw performance. A datastore is admissible only if **permissively licensed**.

| Class | Admissible? | Examples |
|---|---|---|
| Permissive (Apache 2.0 / MIT / BSD / PostgreSQL) | ✅ | Postgres, Qdrant, Kuzu, FAISS, OpenSearch, NATS, Valkey, **RapidOCR (Apache 2.0, implemented offline OCR), Docling (MIT), PaddleOCR / Tesseract / docTR (Apache 2.0)** |
| Weak copyleft (MPL) | ✅ (with note) | RabbitMQ |
| Copyleft (GPL / AGPL) | ❌ default | Neo4j Community (GPLv3), Elasticsearch (AGPL), **MinerU (AGPL)** |
| Source-available / restricted / non-commercial | ❌ | MongoDB, Redis 7.4+, Memgraph, ArangoDB (SSPL/BSL/RSAL); **Surya/Marker (revenue-restricted), Nougat (CC-BY-NC)** |

### C.2 Chosen stack (the R59 allowlist)

| Role | Engine | License | Profile / why | AWS-managed equiv |
|---|---|---|---|---|
| Catalog (relational) | **PostgreSQL** | PostgreSQL | metadata + provenance backbone | RDS / Aurora Postgres |
| Vector — embedded | **FAISS** | MIT | zero-infra local floor | (bundled) |
| Vector — dedicated server | **Qdrant** | Apache 2.0 | production filtering + hybrid; default Vector svc | Qdrant Cloud |
| Vector — in-database | **pgvector** | PostgreSQL | collapses Catalog+Vector; ≤50k-chunk scale | (in RDS) |
| Graph | **Kuzu** | MIT | embedded LPG, fast multi-hop; **MIT beats Neo4j GPL** | self-host EC2/EKS |
| Queue | **NATS JetStream** | Apache 2.0 | light, fast saga transport | SQS |

Stubbed-but-Port-compatible: **OpenSearch** (Apache 2.0 — bridges OSS + AWS-managed +
BM25/kNN hybrid in one engine) and **Weaviate** (BSD-3).

### C.3 Benchmark framing (R23)

The three live vector adapters are deliberately *architecturally distinct*, so the
benchmark compares **categories**, not vendors:
**embedded (FAISS)** vs **dedicated server (Qdrant)** vs **in-database (pgvector)** —
on latency, recall, and resource cost over the golden query set.

### C.4 Enforcement (R59)

A CI license-audit step scans the dependency manifest against the C.1 allowlist and
**fails the build** if any datastore, queue, **or OCR/parsing model** outside the
permissive classes is introduced (this is what disqualified Surya/Nougat/MinerU as OCR
options — R59/R64). This makes "fully open-source, on-prem-legal-clean" a *tested*
property, not a claim.
```
