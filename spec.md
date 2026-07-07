# Spec: Provenance UI Redesign (Living Document)

**Status**: Build-ready · **Approach**: B foundation + C live pipeline
**Source mockup**: `Provenance UI Redesign.html` (screens 1a–1d)
**Deep analysis**: `docs/plans/ui-redesign-plan.md` (impact analysis, alternatives)
**Task checklist**: `todo.md`

> **This is a living document.** Update it when requirements change — not after.
> Every change must be reflected in the **Verification** section. Requirement
> status: `[ ]` not started · `[~]` in progress · `[x]` verified.

---

## Core constraints (must hold throughout)

1. **Byte-identical answers** — live streaming (C) and multi-KB (`kb_ids=[one]`)
   must not change the computed `Answer` for an existing single-KB query. Add
   events; never alter answer computation. (Protects the eval gate: R40–R42, R71.)
2. **Never stream unverified text** — strict groundedness (R31/R32) means the
   user must not see LLM prose until the Critic approves it. Stream *stage events*
   live; stream the *answer text* only after Critic `ok`. (See §9-Q2.)
3. **Additive contracts** — new fields on `EvidenceSet`/`Answer`/`QueryRequest`
   are optional/aliased; regenerate `web/lib/contracts.gen.ts` via
   `scripts/gen_ts_contracts.py` in the same commit (N9 drift check).
4. **Permissive licenses only (R59)** — Plex fonts (OFL), react-force-graph (MIT,
   optional), Vitest/Testing-Library (MIT, dev). CI license-audit must pass.
5. **Truthful UI** — only render agent-stage / saga states the backend actually
   reports. No decorative "Critic ✓" that didn't run.

---

## 0. Locked decisions

| # | Decision |
|---|---|
| D1 | Source inspector = **schematic** bbox highlight (no pdf.js, no file serving) for v1. |
| D2 | Chat history = **in-tab multi-turn** (`turns[]`); no persistence store. |
| D3 | Live pipeline = **now** (Approach C): real per-stage crew events + live ingest SSE feed. |
| D4 | KB selector = **multi** (`kb_ids[]`); accept legacy `kb_id` as alias. |
| D5 | Entity graph = **per-answer subgraph** returned inline on `EvidenceSet`. |

## §9 Open questions — resolved (proposed best solutions)

- **Q1 · Eval under multi-KB** → Keep the golden set **single-KB** (`eval/golden/golden_set.yaml`);
  run the gate with `kb_ids=[one]` as the **parity baseline** and assert scores are
  unchanged vs. today. Defer multi-KB golden cases to a later PR. *Rationale:* isolates
  the fan-out change from answer-quality regressions.
- **Q2 · Token streaming** → The Model service is embed/rerank only; the LLM
  (`LLMClient.complete`) is single-shot and strict groundedness forbids showing
  pre-verification tokens. **Solution:** stream **stage events** live during the
  crew run, and after Critic `ok`, stream the **verified** answer text token-by-token
  by **server-side chunking of the final string** (replacing today's fake word-split).
  This is the *correct* design under R31/R32 — not a fallback. Real LLM-side token
  streaming stays out of scope (would require a streaming LLM backend *and* speculative
  UI that R31/R32 disallows).
- **Q3 · `kb_id` alias lifetime** → Dual-accept `kb_id` (→ `kb_ids=[kb_id]`) for **this
  release only**; remove in the next. Add a deprecation note in the gateway handler.
- **Q4 · Cross-KB domain mismatch** → **Allow multi-select across domains** in v1.
  Query-time retrieval is namespace-based and domain-agnostic (vector `namespace=kb`,
  graph `link/expand` per-kb, then union); domain pinning (R2) governs *ingestion*
  extraction, not query. The Planner already accepts `kb_scope: list[str]` (`crew.py:87`).
  *Constraint:* graph link/expand runs per-KB and results are unioned — no cross-KB
  entity resolution in v1 (flag as a future enhancement).

---

## Requirements

Each requirement has a binary acceptance criterion and a verification method
(see the **Verification** table). Status is tracked inline.

### UI / product requirements

- `[ ]` **R-UI-1 · KB selector (multi)** — the user picks one or more KBs from a
  list instead of pasting an id. *Accept:* the selector is populated from `GET /kb`;
  selecting KB(s) scopes the query (a KB-specific question is answerable only when
  its KB is selected). (R38)
- `[ ]` **R-UI-2 · Live agent pipeline** — the chat shows the 4 crew stages with
  live state and sub-detail; the verified answer then streams token-by-token.
  *Accept:* a query emits ≥4 named stage events (`planner|retriever|critic|synthesizer`)
  over SSE, each rendered in order; a refused query shows `critic` in a `blocked`
  state; answer tokens arrive **only after** a `critic ok` event; no unverified text
  is shown. (R35 + R31/R32)
- `[ ]` **R-UI-3 · Source inspector** — clicking a claim/citation highlights its
  page + bbox. *Accept:* clicking claim 1 renders a highlight at the stored bbox,
  normalized by `page_width/height`; falls back to US-Letter only if dims absent. (R36)
- `[ ]` **R-UI-4 · Honest-refusal card** — a refused answer shows the Critic verdict
  and the specific ungrounded claim(s) + suggested queries. *Accept:* an out-of-corpus
  query renders the refusal card with `refusal_reason` and ≥1 ungrounded claim from the
  Critic verdict; no fabricated citation. (R39/R31)
- `[ ]` **R-UI-5 · Saga stepper** — ingestion shows a 7-stage stepper advancing live.
  *Accept:* uploading a doc advances parse→chunk→detect→extract→graph→embed→vector via
  a live SSE feed (no polling), ending Ready or Failed.
- `[ ]` **R-UI-6 · Detect-but-confirm card** — a domain card with Confirm / Change.
  *Accept:* a doc pauses at `awaiting_confirm`, the card shows detected domain +
  confidence; Confirm resumes; Change overrides the schema and resumes with the chosen
  domain recorded. (R55/R9)
- `[ ]` **R-UI-7 · Multi-turn chat** — multiple turns in one session. *Accept:* two
  sequential questions each render their own answer + inspector state without clobbering
  the first.
- `[ ]` **R-UI-8 · Per-answer entity graph** — named, typed nodes + edges from the
  answer's subgraph. *Accept:* the graph renders entity names/types and ≥1 edge for a
  relational answer, sourced from `evidence.subgraph`. (R37)
- `[ ]` **R-UI-9 · Landing page** — leads with the value proposition. *Accept:* `/`
  renders the value-prop hero + the answer→source visual and links to Ingest/Chat.

### Backend enabling requirements

- `[ ]` **R-BE-1 · List KBs** — `GET /kb` returns `[{id,name,domain_id,created_at}]`
  via a new `Catalog.list_kb()`.
- `[ ]` **R-BE-2 · Multi-KB query path** — `QueryRequest.kb_ids: list[str]` (alias
  `kb_id`) threaded through gateway `/query`+`/query/stream`, query_agent
  `/answer`+`/retrieve`, `run_crew`, and `retrieval.retrieve()` (fan-out + union).
  *Accept:* `kb_ids=[x]` is byte-identical to today's `kb_id=x`; a cross-KB query
  retrieves from all selected KBs.
- `[ ]` **R-BE-3 · Critic verdict surfaced** — the refusal payload carries the
  ungrounded claim(s) (extend `Answer` with an optional `ungrounded_claims`/`verdict`).
- `[ ]` **R-BE-4 · Live crew streaming** — query_agent `/answer/stream` (SSE) emits
  per-stage events + post-verification answer tokens; gateway `/query/stream` proxies
  them through, replacing the fake word-split. Answer bytes unchanged.
- `[ ]` **R-BE-5 · Chunk fetch** — `GET /chunks/{id}` returns `{id,text,page,bbox,...}`
  via `Catalog.get_chunk()` (feeds the inspector; schematic works without text but text
  enriches it).
- `[ ]` **R-BE-6 · Per-stage saga status** — additive `progress` (list of
  `{stage,state,detail}`) on the document, exposed via a live feed; publish the
  currently-silent chunk/graph/vector stages. `document.status` string retained.
- `[ ]` **R-BE-7 · Live ingest SSE** — gateway `GET /documents/{id}/events` forwards
  NATS `ingest.status`; the ingest page consumes it (drops the 40× poll loop).
- `[ ]` **R-BE-8 · Confirm-with-override** — `POST /documents/{id}/confirm` accepts an
  optional `domain_id`/`schema_version`; the saga resumes honoring it and records the choice.
- `[ ]` **R-BE-9 · Per-answer subgraph** — `EvidenceSet.subgraph{nodes[{id,name,type}],
  edges[{src,dst,type}]}`; graph `/expand` returns names/types/edges; the crew populates it.
- `[ ]` **R-BE-10 · Doc provenance exposed** — `GET /documents/{id}` widened with
  detected_domain, detection_confidence, parse_method, ocr_engine, trace_id.

---

## Verification

For each requirement, exactly how completion is proven. New FE tests use Vitest +
Testing Library (added in Task 21); backend tests extend the existing suites.

| Req | Verification method | Location |
|---|---|---|
| R-UI-1 | Component test: KbSelector renders `GET /kb` items, selecting sets `kb_ids`; e2e: KB-specific answer gated on selection | `web/__tests__/KbSelector.test.tsx`; `services/tests/test_gateway.py::test_list_kb` |
| R-UI-2 | Component test: AgentPipeline renders 4 stages in order + `blocked`; asserts tokens only after `critic ok` event | `web/__tests__/AgentPipeline.test.tsx` |
| R-UI-3 | Component test: click citation → highlight style computed from bbox + page dims | `web/__tests__/SourceInspector.test.tsx` |
| R-UI-4 | Component test: refused Answer renders card + ungrounded claim; asserts no citations | `web/__tests__/RefusalCard.test.tsx` |
| R-UI-5 | Component test: SagaStepper advances on mocked SSE events through all 7 stages | `web/__tests__/SagaStepper.test.tsx` |
| R-UI-6 | Component test: confirm/change fire correct payload; integration: override recorded | `web/__tests__/DomainConfirmCard.test.tsx`; `services/tests/test_ingestion.py::test_confirm_override` |
| R-UI-7 | Component test: two `ask()` calls append two turns, first preserved | `web/__tests__/chat_multiturn.test.tsx` |
| R-UI-8 | Component test: EntityGraph renders names/types + an edge from `subgraph` fixture | `web/__tests__/EntityGraph.test.tsx` |
| R-UI-9 | Component test: landing renders hero + nav links | `web/__tests__/landing.test.tsx` |
| R-BE-1 | Unit: `Catalog.list_kb` returns created KBs; route test | `services/tests/test_gateway.py` |
| R-BE-2 | Unit: `retrieve(kb_ids=[x]) == retrieve(kb_id=x)` (parity); cross-KB union test; **eval gate re-run green** | `services/tests/test_retrieval.py`, `test_crew.py`; `eval/tests/test_gate.py` |
| R-BE-3 | Unit: refused crew result includes `ungrounded_claims`; contract regen committed | `services/tests/test_crew.py` |
| R-BE-4 | Unit: `/answer/stream` emits stage events + post-`ok` tokens; gateway proxy forwards them; answer-bytes equality vs `/answer` | `services/tests/test_query_agent.py` (new), `test_gateway.py` |
| R-BE-5 | Unit: `Catalog.get_chunk` + route returns bbox | `services/tests/test_gateway.py` |
| R-BE-6 | Unit: saga publishes all 7 stages; `progress` populated; `status` string unchanged | `services/tests/test_saga.py`, `test_ingestion.py` |
| R-BE-7 | Unit: `/documents/{id}/events` forwards a mocked NATS status event | `services/tests/test_gateway.py` |
| R-BE-8 | Unit: confirm with `domain_id` resumes saga with the override recorded | `services/tests/test_ingestion.py` |
| R-BE-9 | Unit: `/expand` returns nodes/edges; crew fills `EvidenceSet.subgraph`; contract regen | `services/tests/test_graph_store.py`, `test_crew.py` |
| R-BE-10 | Unit: `get_document` returns provenance fields | `services/tests/test_gateway.py` |
| Constraints | Contract drift check green; license-audit green; answer-bytes parity test | `scripts/gen_ts_contracts.py` CI; `eval/tests/test_license_audit.py`; R-BE-2/R-BE-4 parity tests |

---

## Phasing

- **Phase 0 — Foundation**: design system, landing (R-UI-9), `GET /kb` + multi-KB
  selector (R-UI-1, R-BE-1/2), multi-turn chat shell (R-UI-7).
- **Phase 1 — Provenance chat (1a/1b)**: live pipeline (R-UI-2, R-BE-4), inspector
  (R-UI-3, R-BE-5), refusal card (R-UI-4, R-BE-3).
- **Phase 2 — Ingestion saga (1c)**: per-stage status + live feed (R-UI-5, R-BE-6/7),
  confirm/override (R-UI-6, R-BE-8), doc provenance (R-BE-10).
- **Phase 3 — Graph + polish**: per-answer subgraph (R-UI-8, R-BE-9), a11y,
  empty/error states.

Task-level checklist and ordering live in `todo.md`.
