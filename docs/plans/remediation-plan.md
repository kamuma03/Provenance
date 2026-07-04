# Remediation Plan — Code Review 2026-07-03 (commit a1d5617)

Single source for closing all 45 review findings (2 Critical, 13 High, 18 Medium, 12 Low).
Each item lists the **fix**, the **files**, and the **acceptance criterion** (a test or check that
proves it's green — matching the repo's "done = criterion is green" rule). Requirement IDs from
`docs/plans/provenance-requirements.md` are carried through.

Phases are ordered by leverage, not by severity label. Do Phase 0 first: it closes the two
structural holes that make the whole product claim false, plus the cheap high-trust wins.

---

## Phase 0 — The highest-leverage day (correctness of the core promise + honesty + one-liners)

Goal: after this phase, the groundedness invariant is real, CI can catch its regression, and the
docs stop describing infrastructure that doesn't exist.

### 0.1 — Fix the Critic to verify released answer text  `[C-1]`  (R31/R32/R65) — **M**
- **Files:** `services/src/provenance_services/crew.py` (`Synthesizer.synthesize` ~119-127, `Critic.verify` ~171-188, `_llm_grounded` ~196-207)
- **Change:**
  1. When an LLM replaces `answer.text`, decompose that released prose into atomic claims
     (sentence split at minimum) and rebuild `answer.claims` from *those*, so the Critic checks
     what the user actually reads — not the chunk-echo claims that are grounded by construction.
  2. Ground each decomposed claim against the `EvidenceSet`; attach citations at that granularity
     so span-level provenance maps to sentences of the released text.
  3. Make `_llm_grounded`'s failure path **fail closed** (refuse) instead of degrading to the
     trivially-passing token-overlap heuristic.
- **Acceptance:** new test — `run_crew` with `Synthesizer(MockLLMClient(["fabricated: revenue was 999 trillion"]))`
  asserts **refusal**, not release. Existing crew tests still green.

### 0.2 — Make the groundedness eval metric independent of the system's self-report  `[C-2]`  (R41, §9.2) — **M**
- **Files:** `eval/src/provenance_eval/metrics.py` (~49-55), consuming `crew.py` (~238-241)
- **Change:** stop scoring "fraction of claims the Critic marked grounded" (a constant 1.0). Instead
  check released claims against something the system doesn't control — the eval case's **gold span**
  or ingested corpus text (lexical containment is acceptable offline). If the honest choice is that
  no independent signal exists yet, mark it **skipped** (like the RAGAS stubs) rather than fake-green.
- **Acceptance:** feeding a hallucinated answer to the metric yields **< 0.90** (gate fails). The
  existing `test_groundedness_counts_grounded_claims` is replaced with one exercising the real pipeline
  output, not hand-built `Claim(grounded=False)` objects the pipeline can't emit.

### 0.3 — Honest documentation pass  `[H-8]`  — **S**
- **Files:** `README.md` (~49-60 stack table), `ARCHITECTURE.md`, `docs/adr/ADR-001*`, `CLAUDE.md`
- **Change:** replace claims of gRPC/JetStream/LlamaIndex/AutoGen/RAGAS with reality —
  "HTTP/JSON with shared Pydantic contracts; gRPC deferred"; remove the three frameworks from stack
  tables; drop ADR-001's non-existent "versioned-contracts mitigation" or mark it deferred; update
  CLAUDE.md's "greenfield; documentation only" status to reflect the implemented services.
- **Acceptance:** grep of README/ARCHITECTURE/ADR/CLAUDE for `gRPC|JetStream|LlamaIndex|AutoGen|RAGAS`
  returns only lines explicitly marked "deferred/not-yet".

### 0.4 — Five small correctness one-liners
| ID | Fix | File | Acceptance |
|----|-----|------|-----------|
| `[H-2]` | Convert Docling bbox via `bb.to_top_left_origin(page_height)` (page height from `doc.pages[n].size`) so citations aren't vertically mirrored on the default deep-parse path (R6/R36) | `services/src/provenance_services/docling_parser.py:45-49` | cross-backend test: page title's bbox lands in the **top third** under both Docling and pdfplumber (not just `x1>=x0,y1>=y0`) |
| `[M-10]` | `zip(..., strict=True)` so an embeddings/chunks count mismatch raises instead of silently dropping trailing chunks while reporting `done` | `services/src/provenance_services/ingestion.py:84-93` | test: mismatched lengths raise, saga marks `failed` |
| `[H-10]` | Dedicated `PGVECTOR_DSN` env with **no** fallback to the catalog DSN; delete `from .catalog import _dsn` — the only cross-service import (R52) | `services/src/provenance_services/vector_factory.py:13,26` | new R52 test asserting **no shared connection strings** across services |
| `[M-18]` | Replace trailing-`&&` with an explicit `if` so a successful default run exits 0; make `--no-pull` actually skip the pull-profile service | `scripts/start.sh:84` | `start.sh && echo ok` prints `ok`; `--no-pull` runs no pull container |
| `[H-3d]` | Add a `pg_data` volume to Postgres (currently only the init script is mounted → catalog lost on container recreation while `kuzu_data` survives = split-brain) | `ops/docker-compose.yml:47-55` | `docker compose down && up` preserves catalog rows |

---

> **Status (updated):** Phases 0 ✅, 1 ✅, and 2 ✅ are implemented, tested, and green
> (ruff + mypy + 141 passing tests + eval gate + license audit; web lint/tsc/build pass).
> **Deferred follow-ups** (larger or untestable-here, left as honest notes):
> - H-13: non-root container user, `uv sync --frozen`, pinning the `ghcr.io/astral-sh/uv` copy
>   source (Docker image build can't be exercised in this environment).
> - M-5: only the **gateway query edge** is typed with Pydantic request models so far (validation +
>   OpenAPI at the edge, N9). Typing every internal service endpoint and **generating the web TS
>   types from OpenAPI in CI** is the larger remaining half.
> - M-3: the detect-but-confirm **resume** flow (R55) — the PAUSED outcome is now reported, but
>   interactive confirmation + saga resume is not built.
> - M-14: client caching / startup route validation (the concrete null-content / truncation /
>   max-tokens bugs are fixed).
> - M-17: a **web service in the compose stack** and pre-baking the HuggingFace reranker export for
>   air-gapped rebuilds (the `.dockerignore` and the ingest-page O(n²) base64 freeze are fixed).
>
> The remaining web `npm audit` highs (`glob` dev-only, `next`/`postcss`) require a breaking Next
> 15/16 major and are out of scope; the critical CVE is fixed by the 14.2.33 bump.
> Phase 3 (Low) remains open.

## Phase 1 — Groundedness & retrieval robustness (this cycle, High severity)

### 1.1 — Per-chunk graph extraction over the whole document  `[H-1]`  — **M**
- **File:** `services/src/provenance_services/ingestion.py:52-64`
- **Change:** `_extract_step` currently reuses the 2,000-char detection `sample` as its entire input,
  so entities/relations past ~page 2 never reach Kuzu. Extract **per chunk**, batched through the
  low LLM tier (extraction already routes to the cheap model); keep the sample for detection only.
- **Acceptance:** eval document **longer than 2,000 chars** with a gold entity beyond the window;
  test asserts that entity reaches the graph.

### 1.2 — Wire verdict feedback into synthesis so REVISE actually revises  `[M-1]`  (R32) — **M**
- **File:** `crew.py:109-111,232-241`
- **Change:** `synthesize(plan, evidences, verdict)` ignores `prev`; feed `verdict.ungrounded_claims`
  into the next synthesis and short-circuit when deterministic (identical output → refuse immediately).
- **Acceptance:** test: a REVISE iteration produces **different** text (or refuses) rather than a
  byte-identical replay.

### 1.3 — Real idempotent upload  `[H-4]`  (N5) — **M**
- **Files:** `gateway.py:90-108`, `catalog.py:70-82`
- **Change:** `INSERT … ON CONFLICT DO NOTHING RETURNING id` (or pre-check); on conflict return the
  **existing** document id and **skip** the publish (currently a re-upload mints a dangling id that
  404s forever *and* re-runs the full saga, appending duplicate chunks). Validate `content_b64` and
  return **400** on malformed base64 instead of an unhandled 500.
- **Acceptance:** test: re-uploading identical content returns the original id and publishes **zero**
  new jobs; malformed base64 → 400.

### 1.4 — Thread-pool blocking work off the event loop  `[H-5]`  — **M**
- **Files:** `model.py:24-36`, `graph.py:53-92`, `parse.py:40-52`, qdrant/faiss store methods
- **Change:** wrap ONNX embed/rerank, Kuzu cursors, and Docling/OCR parses in
  `await anyio.to_thread.run_sync(...)` so `/health` and `/ready` keep answering under load. Mind the
  non-thread-safe lazy OCR singleton — initialize eagerly or lock. Push `/link` into a Kuzu-side query
  (currently scans every entity per query — O(corpus)); batch `_expand`'s per-entity HTTP fan-out into one call.
- **Acceptance:** test: `/health` responds while a synthetic slow embed runs; `/link` latency flat as
  entity count grows (micro-benchmark or query-shape assertion).

### 1.5 — Graceful degradation on graph/rerank failure — preserve the vector floor  `[H-6]`  (R25) — **S**
- **Files:** `retrieval.py:39-56`, `clients.py:29-35`
- **Change:** `try/except` around `link`/`expand` → empty lift with `graph_expanded=False` + span
  attribute; around `rerank` → keep hybrid fusion order. A Graph or Model outage must not 500 the query.
- **Acceptance:** test: with Graph client raising, retrieval still returns vector evidence and sets
  `graph_expanded=False`.

### 1.6 — Fail-fast instead of silent hash-embedding fallback  `[H-7]`  (R66) — **S**
- **Files:** `embedder.py:73-81`, `reranker.py:105-118`, `vector.py`
- **Change:** outside `PROVENANCE_OFFLINE`, **fail startup** (or at minimum ERROR-log + expose
  `model_id` in `/ready`) rather than degrading to `DeterministicEmbedder` (SHA-256 pseudo-vectors that
  silently coexist with real bge-small in the same namespace). Have Vector record `model_id` per
  namespace on first upsert and **reject mismatches** — implement what the embedder docstring already claims.
- **Acceptance:** test: constructing the real embedder under a simulated failure with offline **unset**
  raises at startup; Vector rejects an upsert whose `model_id` differs from the namespace's recorded one.

### 1.7 — Durability: JetStream + real compensations + delete endpoints  `[H-3a,b,c]`  (R54) — **L**
- **Files:** `ingestion.py:33-37`, `nats_client.py:31-65`, `faiss_store.py`, plus new Vector/Graph delete endpoints, `ops/docker-compose.online.yml`
- **Change:**
  - JetStream **durable consumers** with explicit ack **after** saga completion (the server already
    runs `-js`; the client uses core pub/sub → at-most-once, lost job on restart → doc stuck forever).
  - **DELETE-by-document** endpoints on Vector and Graph, wired into `_compensate` (today it only logs).
  - Default the online overlay to a **persistent** vector backend (qdrant/pgvector) instead of
    in-memory FAISS (which `docker compose restart vector` silently erases while the catalog says `done`).
- **Acceptance:** test: kill the consumer mid-saga → job redelivered, document reaches a terminal state;
  a failed embed after `write_graph` triggers a real graph delete (no orphaned entities citing absent chunks).

### 1.8 — Persist provenance to the Document row  `[H-9]`  (R56) — **M**
- **Files:** `catalog.py:84-89`, `gateway.py:36-39`, `ingestion.py:108-110`, `ops/sql/catalog_init.sql:19-41`
- **Change:** extend the status event to carry the provenance payload
  (`detected_domain`, `detection_confidence`, `schema_version`, `parse_method`, `ocr_engine`, `trace_id`)
  and persist it on `done`. Populate the `chunk` table (currently dead schema) or delete it. Make the
  intermediate statuses (`DETECTING`, `EXTRACTING`, `AWAITING_CONFIRM`) reachable or remove them.
- **Acceptance:** test (R56 criterion): the Document row stores the correlating `trace_id` after ingestion.

### 1.9 — Deployment surface hardening  `[H-13]`  — **S each**
- **Files:** `ops/docker-compose.yml:44-106`, `.github/workflows/ci.yml`, `web/package.json:13`
- **Change:**
  - Bind datastores to **loopback** (or drop host publishing) for everything but the gateway; interpolate
    Postgres creds from `.env` (currently `change-me` hardcoded twice — editing `.env` does nothing).
  - Scope `ANTHROPIC_API_KEY` to the containers that need it, not all 8.
  - Add a **web CI job**: `npm ci && lint && tsc && build && npm audit`; bump `next` to latest 14.2.x patch
    (current `14.2.15` carries a critical advisory chain).
  - Pin `ollama:latest` and the uv copy source; use `uv sync --frozen` in the Dockerfile (currently
    `uv pip install -e` does a fresh resolution → images can diverge from the lockfile CI tested).
  - Add non-root users + healthchecks to containers.
- **Acceptance:** CI runs the Node job and fails on lint/type/audit errors; `docker compose config`
  shows datastores bound to `127.0.0.1`; `npm audit` clean at moderate+.

### 1.10 — Text-beside-table dedup ignores the x-axis  `[H-11]`  — **S**
- **File:** `services/src/provenance_services/parse_engine.py:41-44,74-78`
- **Change:** `_center_in` drops any line whose vertical center falls in a table's vertical span with
  **no horizontal check** — left-column prose beside a right-column table is deleted from the corpus
  (flagship financial-filing layout). Require horizontal overlap too (`x0 <= cx <= x1`).
- **Acceptance:** two-column fixture in the parse tests: prose beside a table survives to chunks.

### 1.11 — Eval circularity + license-audit PEP 639 blind spot  `[H-12]`  (R59) — **M / S**
- **Files:** `eval/golden/eval_set.yaml:22-27` with `services/.../detection.py:35-43`; `scripts/license_audit.py:23-33`
- **Change:**
  - Replace detection eval cases (currently the registry's own signal vocabulary stitched into
    sentences — measuring keywords matching themselves) with **held-out realistic prose** snippets,
    3–5 per domain.
  - Add `License-Expression` (PEP 639 SPDX) to the audit's signals; **warn/fail** on distributions
    with no license metadata (60 installed dists declare license only via `License-Expression` and are
    invisible today; 10 more with none pass silently → a modern-packaged GPL dep sails through R59).
- **Acceptance:** audit flags a synthetic `License-Expression: GPL-3.0-only` dist; detection metric
  computed on held-out prose still ≥ 0.90.

---

## Phase 2 — Medium findings (correctness, safety, contracts, ops)

Grouped by theme. Each is verified-against-source per the review.

### 2.1 — Groundedness & metric correctness
| ID | Fix | File |
|----|-----|------|
| `[M-2]` | Numeric exact-match is substring-based — whitespace stripping lets `"14.2 billion"` pass for expected `"4.2 billion"`. Add boundary-aware matching + the `14.2` counter-example test (R42, strictest §9.2 gate) | `eval/.../metrics.py:36-44` |
| `[M-4]` | Prompt-injection at the release gate: raw ingested text flows into the Critic prompt and verdict is `startswith("YES")` on unconstrained output. Delimit untrusted content; require exact-match tokens; fail closed | `crew.py:196-207` |

### 2.2 — Graph provenance & extraction robustness
| ID | Fix | File |
|----|-----|------|
| `[M-6]` | Relation provenance is last-writer-wins (`MERGE … SET r.document_id`) — a second document overwrites the source. Make it additive (R56) | `graph_store.py:56-62` |
| `[M-7]` | Relations dropped on surface-form mismatch — endpoint lookup bypasses the resolver's normalization. Normalize the lookup; report `relations_dropped` | `graph.py:56-64` |
| `[M-8]` | LLM output items unvalidated pre-Pydantic; one malformed entity 500s `/extract`, garbled JSON silently yields empty graph. Extend repair-by-dropping to shape; log the fallback | `extraction_engine.py:69-71,98-102` |

### 2.3 — Ingestion durability & correctness
| ID | Fix | File |
|----|-----|------|
| `[M-3]` | Detect-but-confirm (R9/R55) unwired — `needs_confirmation` discarded, `SagaPause` never raised, `AWAITING_CONFIRM` unreachable. Wire it or explicitly mark deferred | `ingestion.py:52-58,127-132` |
| `[M-9]` | Chunker overlap-carry emits duplicate tail chunks at page/doc boundaries → duplicate embeddings/citations. Fix carry logic; add a multi-chunk test with `overlap_chars > 0` | `chunker.py:57-61,81-88` |
| `[M-11]` | Ingestion consumer has no failure containment — an exception escapes the NATS callback, doc stuck non-terminal. Wrap, best-effort publish `failed`, add a reconciliation sweep | `ingestion.py:113-132` |
| `[M-12]` | Silent unlogged fallbacks: Docling→pdfplumber (any-exception), swallowed compensation errors, catalog writes dropped when pool absent while gateway returns success ids. Narrow, log, span-attribute | `parse.py:35-36`, `saga.py:68-69`, `catalog.py:61-87` |
| `[M-13]` | `parse_method` provenance wrong for mixed/Docling docs — "dominant method" decided by page 0; scanned Docling docs recorded `text_layer` with empty `page_methods` (R63). Compute per-page truthfully | `parse_engine.py:109-110`, `docling_parser.py:91-92` |

### 2.4 — Contracts & LLM client
| ID | Fix | File |
|----|-----|------|
| `[M-5]` | No contract enforcement at any HTTP boundary — `req.json()` + `.get()` with silent defaults (missing `kb_id` → `"default"`); empty OpenAPI; hand-copied TS types (N9). Type endpoints with existing Pydantic contracts; generate TS from OpenAPI in CI | all service endpoints, `web/lib/types.ts` |
| `[M-14]` | LLM client: `str(None)` on null content; hardcoded `max_tokens=1024` with `stop_reason` never checked (truncated answers released as complete); fresh clients per request; unknown-provider raises per-request while missing keys silently degrade. Validate specs at startup; check stop reasons; cache clients | `packages/service/.../llm.py:50-106,145-151` |

### 2.5 — Edge / SSE / web
| ID | Fix | File |
|----|-----|------|
| `[M-15]` | SSE: no `error` event (outage → infinite spinner); retrieval runs **twice** per streamed query; `done` evidence may not match the answer's citations (R36); client never checks `res.ok`, no `AbortController`, Enter bypasses the busy guard → interleaved answers. Emit error events; retrieve once; guard input | `gateway.py:130-151`, `web/lib/api.ts:43-86`, `web/app/chat/page.tsx:27-59` |
| `[M-16]` | Telemetry module-global binds all in-process apps to the first service's identity — misattributed `service.name` for the eval harness. Make service identity per-app, not module-global | `packages/service/.../telemetry.py:18-46` |
| `[M-17]` | Ops hygiene: web UI absent from the compose stack (manual `next dev` + permissive CORS); one multi-GB CUDA image for all 8 services; no `.dockerignore` (repo + `web/node_modules` shipped ×8); build-time HF download breaks air-gapped rebuilds; ingest page freezes tab base64-encoding 50MB per-byte; status poll silently expires at 40s | `ops/`, `web/app/ingest/page.tsx` |

---

## Phase 3 — Low findings (polish, hardening, DX)

| ID | Fix | File |
|----|-----|------|
| `[L-1]` | `merged/created` counts in graph `/write` always wrong — `known_ids` never passed | `graph.py:53` |
| `[L-2]` | `heuristic_generic` turns sentence-initial "The"/"This" into Concept entities | `extraction_engine.py:30-43` |
| `[L-3]` | `Catalog._ensure` race can leak a pool — add an `asyncio.Lock` | `catalog.py:33-42` |
| `[L-4]` | Fresh `httpx.AsyncClient` (new pool) per inter-service call, no retries — reuse a client, add retry | `clients.py:29-44` |
| `[L-5]` | `needs_deep_parse` probe runs full-doc `find_tables()` then parse repeats it; `except → True` unlogged | `parse_engine.py:22-38` |
| `[L-6]` | Gate plumbing: metrics/thresholds drift → `KeyError` in one loop, silent ungate in the other; `main()` ignores argv; data paths break on wheel installs | `eval/.../gate.py:60-75` |
| `[L-7]` | Readiness-probe exceptions become 500s, not the documented 503 | `packages/service/.../app.py:48-55` |
| `[L-8]` | Eval set too small for its thresholds (~2 out-of-corpus cases behind a 0.90 gate — one flake = 50-pt swing); `_STOPWORDS` contains "personal" adjacent to an eval query — comment/test it isn't load-bearing | `eval/golden/`, detection |
| `[L-9]` | SQL: no `chunk(kb_id)` index, no `status` CHECK constraint (typo'd status → UI polls forever), no migration story once a data volume exists | `ops/sql/catalog_init.sql:32-44` |
| `[L-10]` | Web a11y: citation spans click-only (no `role`/`tabIndex`/keyboard — core feature invisible to screen readers); labels lack `htmlFor`; no `aria-live` on streaming; `as`-casts on the drift-prone payload boundary; bbox math hardcodes US-Letter 612×792 — carry page dims in the Citation contract | `web/components/CitationPanel.tsx:48-49` |
| `[L-11]` | GPU overlay grants CUDA + `PROVENANCE_ONNX_CUDA` to `query-agent`, which hosts no models — dead config contradicting N7 | `ops/docker-compose.gpu.yml` |
| `[L-12]` | OTel debug exporter at `verbosity: detailed` will print document content into logs once spans carry chunk text; benchmark crashes on empty query sets, uses a floor-index p95 | `ops/otel-collector.yaml:12-14`, `eval/.../benchmark.py` |

---

## Sequencing & effort summary

| Phase | Contents | Rough effort |
|-------|----------|--------------|
| **0** | C-1, C-2, H-8 docs, + 5 one-liners (H-2, M-10, H-10, M-18, H-3d) | ~1 day |
| **1** | H-1, H-3(a-c), H-4, H-5, H-6, H-7, H-9, H-11, H-12, H-13, M-1 | ~1–2 weeks |
| **2** | 18 Medium (grouped 2.1–2.5) | ~1–2 weeks |
| **3** | 12 Low | ~2–3 days |

Total remediation ≈ 17×S, 13×M, 2×L, plus the optional XL (real gRPC) which is explicitly
**deferred** — H-8 makes the docs honest about that rather than implementing it.

### Guardrails while executing (from CLAUDE.md invariants)
- Keep changes **inside the owning service**; surface any contract/schema change explicitly (R57/N9).
- Don't add a 5th agent or split the crew (ADR-001); keep entity resolution in Graph.
- No non-permissive dependency (the H-12 audit fix must not itself pull GPL tooling).
- Every "done" = its acceptance criterion green in CI. Add the **missing tests** noted per item —
  the review's core lesson is that the composition layers (gateway, ingestion service, model/vector/
  graph endpoints, NATS client, telemetry) have **zero coverage**, which is exactly where the High
  findings live.
