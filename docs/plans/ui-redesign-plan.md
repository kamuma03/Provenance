# Feature Plan: Provenance UI Redesign

**Date**: 2026-07-06
**Project**: Provenance (provenance-aware RAG + KG)
**Status**: Planning — decisions locked (see §0)
**Source spec**: `Provenance UI Redesign.html` (design mockup — screens 1a–1d)

## 0. Locked Decisions & Deltas

Five decisions taken in review. They move the chosen approach from **B** to
**B (foundation) + C (live pipeline)**, and two of them (multi-KB, live crew
streaming) touch the **eval-sensitive query path** — so backend/architecture
impact and risk rise accordingly. Deltas below override the original text where
they conflict.

| # | Decision | Delta |
|---|---|---|
| 1 | **Source inspector = schematic highlight (v1)** | No pdf.js, no original-file serving. Keeps §3.8 low. Task 20 loses the PDF sub-item. |
| 2 | **Chat history = in-tab multi-turn** | No persistence store. `turns[]` only (Task 5). No new Catalog table. |
| 3 | **Live pipeline = now (Approach C)** | Crew stage/token streaming + NATS→SSE ingest feed become **in scope**, not Phase-4-optional. New internal streaming hop `query_agent /answer/stream`; gateway proxies it; ingest page drops its polling loop for a live SSE feed. Raises Architecture→Med-High, Backend→High, Perf→Med. **Answer computation must stay byte-identical — add events only.** |
| 4 | **KB selector = multi (`kb_ids[]`)** | **Query-path contract change** on `QueryRequest` (`kb_id` → `kb_ids[]`), threading through gateway `/query`+`/query/stream`, query_agent `/answer`+`/retrieve`, Planner KB-scope (R29), and `retrieval.retrieve()`. Retrieval now **fans out across KBs per subquery** (more vector/graph calls). **Eval impact: golden set is single-KB — re-run the gate; treat `kb_ids=[one]` as identical to today's path.** Accept legacy `kb_id` as an alias during a dual-running period. |
| 5 | **Entity graph = per-answer subgraph** | Extend `EvidenceSet` with an additive `subgraph{nodes[{id,name,type}], edges[{src,dst,type}]}`; the crew's existing link+expand returns it (graph `/expand` must surface names/types/edges, not just ids). Replaces Task 16's "resolve ids on demand" with "return subgraph inline." |

**Net scope change:** in — live crew stage+token streaming, live ingest SSE feed,
multi-KB query path, per-answer subgraph. Out (unchanged) — pdf.js render,
persisted conversations, auth.

## 1. Overview

### Goal
Turn the current three thin utility pages (`/`, `/ingest`, `/chat`) into a
product-grade UI that makes the system's core promise **visible**: every answer
traced to a source span, an honest-refusal state with a real Critic verdict, the
4-agent crew shown working, and the ingestion saga shown progressing. The
redesign is, to a large degree, the **UI realization of requirements that already
exist but are implemented minimally** (R35–R39 chat/citations/graph/refusal/KB-scope;
R55 detect-but-confirm). It is *not* a new capability domain.

### Scope
**In scope**
- Reskin all pages to the mockup's design system (Plex Sans/Serif/Mono, semantic 3-colour palette, dark theme).
- Landing page that leads with the value proposition (1d).
- Knowledge-base **selector** replacing the raw `kb_…` paste (needs a list endpoint).
- Multi-turn chat history (client-side).
- Visible **agent-crew pipeline** (Planner→Retriever→Critic→Synthesizer) with per-stage state.
- **Source inspector**: click a citation → highlight page + bbox.
- **Honest-refusal** state with the Critic's verdict + suggested queries.
- **Ingestion saga** stepper (7 stages), domain detect-but-confirm card, live counts.
- Entity graph mini-view with named/typed nodes + edges.

**Out of scope (v1)**
- Server-side persisted conversation history / accounts (chat stays stateless per query; history is in-tab).
- Real page-image / PDF.js rendering of source documents (schematic highlight retained unless Approach C is chosen).
- Authentication / multi-tenant authz (not present today; the redesign does not add it — see Security).
- Light-theme variant, mobile layout polish (mockup is desktop dark; note as follow-on).

## 2. Requirements

| # | Requirement | Acceptance criterion |
|---|---|---|
| R-UI-1 | The user can pick a KB from a list instead of pasting an id. | Verified when: the chat KB selector is populated from `GET /kb` and selecting one scopes the query (asserts a KB-specific answer, per R38). |
| R-UI-2 | The chat shows the 4 crew stages with live state (active/done/blocked) and sub-detail (chunk count, "Critic blocked"). | Verified when: a query emits ≥4 named stage events over SSE and the pipeline bar reflects each; a refused query shows Critic in a `blocked` state. |
| R-UI-3 | Clicking a claim/citation highlights its page + bbox in the source inspector. | Verified when: clicking claim 1 renders a highlight at the stored bbox (page + x0/y0/x1/y1), normalized by `page_width/height` (R36). |
| R-UI-4 | A refused answer shows the honest-refusal card with the Critic verdict and the ungrounded claim(s). | Verified when: an out-of-corpus query renders the refusal state, `refusal_reason`, and the specific ungrounded claim from the Critic verdict; no fabricated citation (R39). |
| R-UI-5 | Ingestion shows a 7-stage saga stepper that advances as the document processes. | Verified when: uploading a doc advances the stepper through parse→chunk→detect→extract→graph→embed→vector, ending Ready (or Failed). |
| R-UI-6 | Detect-but-confirm surfaces a domain card with Confirm / Change. | Verified when: a doc pauses at `awaiting_confirm`, the card shows detected domain + confidence, Confirm resumes it, Change overrides the schema (R55/R9). |
| R-UI-7 | The chat supports multiple turns in one session. | Verified when: two sequential questions both render with their own answer + inspector state, without clobbering the first. |
| R-UI-8 | The entity graph shows named, typed nodes and edges used in the answer. | Verified when: the graph renders entity **names/types** and ≥1 edge for a relational answer (R37), not raw ids. |

## 3. Impact Analysis

The redesign is mostly **frontend + a set of small, additive backend read
endpoints**. The one genuinely invasive item is making the agent pipeline *live*
(Approach C). Below, "gap" = something the mockup shows that the backend does not
yet expose.

### 3.1 Architecture — **Low–Medium**
- Additive: new read endpoints on the Gateway (list KB, get chunk, KB subgraph, richer doc/provenance, per-stage saga status). No new services.
- The Gateway remains the only browser edge (R51); all new routes proxy Catalog/Graph as existing ones do (`clients.call`/`call_get`).
- **Invasive only if live pipeline is chosen (C):** threading a stage-event emitter through `run_crew` (`crew.py:268`) → `query_agent` `/answer` (`query_agent.py:79`) → Gateway SSE. That crosses the "keep the crew in one service" non-split (ADR-001) but does not violate it — it's a callback, not a split. Also touches the currently-**fake** token stream (Gateway computes the full answer then re-emits it word-by-word, `gateway.py:180-198`).

### 3.2 UI / UX — **High** (this is the point of the work)
- New/rebuilt: landing (1d), chat grounded (1a), chat refusal (1b), ingest saga (1c).
- New interactions: KB dropdown, claim→inspector linking, multi-turn thread, saga stepper, domain confirm/change, suggested-query chips.
- Accessibility: keep the existing keyboard-accessible citation pattern (`CitationPanel.tsx:26-32`, review L-10) and `aria-live` status region (`chat/page.tsx:85`). New pipeline/stepper need `role`/`aria-label`.
- Responsive: mockup is fixed-width desktop dark; a fluid/mobile pass is follow-on.

### 3.3 Frontend — **High**
- Design system: add `@fontsource`/self-hosted **IBM Plex Sans/Serif/Mono** (air-gap: bundle, don't hotlink Google Fonts). Rework `globals.css` tokens to the mockup palette (`#5e8bff` interaction / `#35c990` grounded / `#f0a83a` refusal).
- State: chat `turn` → `turns[]` (`chat/page.tsx:11-15`); selected-citation state lifts from `CitationPanel` to page level so the inspector column reacts.
- Components: `KbSelector`, `AgentPipeline`, `SourceInspector` (replaces/extends `CitationPanel`), `RefusalCard`, `SagaStepper`, `DomainConfirmCard`; upgrade `EntityGraph` to named/typed + edges.
- API client (`lib/api.ts`): add `listKbs`, `getChunk`, `getKbGraph`, `confirmDocument(override?)`, and richer status consumption. Existing `streamQuery` handlers extend for named stages.
- Deps (new): a graph lib is optional — `EntityGraph` is already dependency-free SVG; upgrading to `react-force-graph` (MIT) is optional. PDF render (C) → `pdfjs-dist` (Apache-2.0). Both permissive (R59 ✓ — verify in CI license-audit).
- Bundle: fonts + optional graph/pdf libs add weight; lazy-load the inspector/pdf.

### 3.4 Backend — **Medium** (additive), **High** only for live pipeline (C)
Confirmed gaps vs. mockup (file refs from the current tree):
1. **No `GET /kb` list** — only `POST /kb` exists; `Catalog` has no `list_kb` (`catalog.py`). **Add** `Catalog.list_kb()` + Gateway `GET /kb`. *(unblocks R-UI-1)*
2. **No chunk/page fetch for the inspector** — citations carry `chunk_id/page/bbox`, but there is no `GET /chunks/{id}`. **Add** `Catalog.get_chunk()` + Gateway route. *(unblocks R-UI-3 real content; schematic works without it)*
3. **Critic verdict not surfaced** — refusal is `Answer(refused, refusal_reason)`; `Verdict.ungrounded_claims` (`messages.py:81`) is internal. **Add** the ungrounded claim(s) to the refusal payload (extend `Answer` or add a `verdict` field). *(unblocks R-UI-4)*
4. **Coarse ingestion status** — a single string on `document.status` (parsing/detecting/extracting/embedding/awaiting_confirm/done/failed); the structured `SagaOutcome` and chunk/graph/vector sub-stages are never exposed. **Add** a per-stage status feed (new field or `GET /documents/{id}/progress`). *(unblocks R-UI-5)*
5. **Detect-but-confirm exists but is one-way** — `POST /documents/{id}/confirm` resumes with `confirmed=True` (`gateway.py:156`, `ingestion.py:276`); there is no **override** to a different domain. **Extend** confirm to accept an optional `domain_id`/`schema_version`. *(unblocks R-UI-6 "Change")*
6. **Entity graph is ids only** — evidence carries `entity_ids` + `graph_expanded`; no names/types/edges via the Gateway (graph `/expand` is internal; only `/stats` is proxied). **Add** a Gateway-proxied `GET /kb/{id}/graph` (or resolve entity ids→details). *(unblocks R-UI-8)*
7. **Doc provenance not exposed** — `GET /documents/{id}` returns only `id,kb_id,source,status`; detected_domain/confidence/parse_method/ocr_engine/trace_id are persisted (`catalog.py:129-140`) but hidden. **Widen** the response. *(supports 1c provenance detail)*
8. **(C only) Live crew streaming** — `run_crew` is synchronous with no hooks; the SSE token stream is synthetic. Real staged/token streaming needs an emitter through crew→query_agent→gateway.

### 3.5 Data — **Low**
- No schema changes required for A/B. New reads only.
- Item 4 (per-stage status): prefer **additive** — keep the `document.status` string, add a `stages`/`progress` JSON column or a separate progress store — rather than repurposing `status`, which the current UI and `_on_status` handler depend on (`gateway.py:56-65`). Avoids a breaking migration.
- Item 3 (verdict in Answer): additive optional field → regenerates `contracts.gen.ts` (N9). All services tolerate an added optional field.

### 3.6 Security — **Low (in the air-gapped model), but note**
- New `GET` endpoints (list KB, get chunk, subgraph) **widen the read surface**: KBs become enumerable and chunk text becomes fetchable by id. There is **no auth** in the Gateway today; new routes inherit that. Acceptable for the single-tenant/on-prem/air-gapped deployment model, but explicitly a new enumeration surface — flag for any future multi-tenant posture.
- Input validation: chunk-id/kb-id path params must be validated (avoid injection into Catalog queries).
- No new file-upload surface (upload already exists). Bundling fonts locally *removes* the external Google Fonts request (good for air-gap).

### 3.7 Safety (AI/ML) — **None (net positive)**
- No model/prompt/guardrail changes. The redesign **strengthens** the safety story by making strict refusal (R31/R32) and the Critic verdict *legible*. Surfacing ungrounded claims must show the Critic's actual verdict — never a client-side heuristic that could mislead about groundedness.

### 3.8 Performance — **Low (B), Medium (C)**
- B: extra reads are small point lookups; schematic inspector is free; pipeline uses the existing SSE.
- C: live streaming holds SSE connections for the full crew run; a NATS→SSE bridge for ingestion adds a subscription per open ingest page; pdf.js page render is client-side CPU. All bounded and lazy-loadable.

### 3.9 Testing — **Medium**
- Backend: unit tests for `list_kb`, `get_chunk`, confirm-with-override, per-stage status, subgraph; extend `test_gateway.py`, `test_crew.py` (verdict surfacing), `test_saga.py`/`test_ingestion.py` (status feed).
- Frontend: component tests for KbSelector, AgentPipeline states (incl. blocked), SourceInspector highlight math, RefusalCard, SagaStepper, multi-turn. No FE test harness exists today (only `eslint`+`tsc`) — adding Vitest + Testing Library is a small new dependency (MIT).
- Contract: `scripts/gen_ts_contracts.py` drift check must pass after any contract field additions (N9).
- Eval gate unaffected (no retrieval/answer logic change) unless C alters streaming semantics — keep answer content identical.

### 3.10 Dependencies & licensing — **Low**
- New: IBM Plex fonts (OFL — permissive, redistributable), optional `react-force-graph` (MIT), optional `pdfjs-dist` (Apache-2.0), dev-only Vitest/Testing Library (MIT). All pass the R59 permissive-only rule; **run the CI license-audit** to confirm no transitive SSPL/BSL/GPL.

### 3.11 DevOps & deployment — **Low**
- No new services/ports. Fonts bundled into the Next.js build. New Gateway routes are same-container. No env changes for A/B; C's ingestion live feed may want a Gateway SSE route for status (reuses the existing NATS subscription in `_on_status`).
- Rollback: additive endpoints + a frontend rebuild — revert the web build and drop the unused routes; no data migration to unwind (if item 4 stays additive).

### 3.12 Risk assessment — **Medium overall**
- Biggest risk sits in Approach C (live pipeline): touching `run_crew`/query_agent streaming risks altering answer/eval behaviour and the R35 stream contract. Mitigate by keeping answer computation unchanged and only *adding* stage events.
- Faking pipeline states (Approach A) risks **misrepresenting** the system — a decorative "Critic ✓" that didn't actually run would betray the provenance ethos. Avoid: only show stage states the backend actually reports.

### Impact Summary
| Dimension | Impact | Key concern |
|---|---|---|
| Architecture | **Med–High** (locked C) | Additive endpoints + internal streaming hop; crew stage events |
| UI/UX | High | Four screens rebuilt; new interactions |
| Frontend | High | Design system, multi-turn state, new components, SSE stage/token handling |
| Backend | **High** (locked C+multi-KB) | Additive reads + `kb_ids[]` query-path change + streaming endpoints + subgraph |
| Data | Low | No schema change; keep status additive |
| Security | Low | New read/enumeration surface, no auth (air-gap OK) |
| Safety | **Low (+)** | Legible refusal/verdict (+); but multi-KB changes retrieval scope → re-run eval gate |
| Performance | **Med** (locked C) | Live SSE holds connections; multi-KB fans retrieval across KBs |
| Testing | Med | New FE test harness; gateway/crew/saga tests |
| Dependencies | Low | Fonts + optional graph/pdf, all permissive |
| DevOps | Low | No new infra; additive rollback |

## 4. Alternative Approaches

| Aspect | A · Reskin only | B · Reskin + thin read endpoints (recommended) | C · Full live pipeline + real inspector |
|---|---|---|---|
| Summary | New design system + multi-turn; KB via localStorage/paste; pipeline & saga are post-hoc/decorative; schematic bbox | A + additive endpoints (list KB, get chunk, verdict, per-stage saga, confirm-override, subgraph) so every panel shows **real** data | B + live crew stage/token streaming + NATS→SSE ingest feed + pdf.js page render |
| Architecture impact | Low | Low–Med | Med–High |
| Effort | S–M | M–L | XL |
| Risk | Low (but integrity risk: faked states) | Low–Med | Med–High (touches crew/streaming/eval) |
| Pros | Fast; no backend | Honest; unlocks 1a/1b/1c/1d truthfully; still additive & reversible | Fully matches mockup fidelity |
| Cons | Pipeline/saga misrepresent reality; KB list still absent | No real-time crew animation (coarse stage events); schematic (not PDF) inspector | Invasive; must not disturb answer/eval behaviour; PDF storage/serving needed |
| Best when | Demo-only reskin | **Shipping the redesign properly on the current architecture** | A later fidelity pass once B is stable |

**Recommendation: B.** It realizes every mockup screen with truthful data on the
existing architecture, stays additive/reversible, and defers the one invasive
piece (live crew streaming, C) to a follow-on — which can layer on top of B
without rework.

> **Locked (see §0): B foundation + C now.** The team elected to bring live crew
> streaming (C) forward and add multi-KB scope + a per-answer subgraph. Schematic
> inspector and in-tab history stay as B. The invasive items (crew streaming,
> `kb_ids[]`) touch the query path — see §0 deltas and the eval caveat.

## 5. Implementation Plan (Approach B)

Work backwards from the flagship screen (1a). Ship the design system + landing +
KB selector first (unblocks everything), then the chat provenance view, then the
ingestion saga, with backend endpoints landing just ahead of the FE that needs them.

### Phases
- **Phase 0 — Foundation**: design system (fonts, tokens, nav), landing (1d), `GET /kb` + KB selector, chat reskin as multi-turn. *Ships a coherent redesign even if later phases slip.*
- **Phase 1 — Provenance chat (1a/1b)**: agent pipeline (coarse stage events), source inspector wired to citations, refusal card with Critic verdict.
- **Phase 2 — Ingestion saga (1c)**: per-stage status feed, saga stepper, detect-but-confirm card (+ override), richer doc provenance.
- **Phase 3 — Graph + polish**: named/typed entity graph via subgraph endpoint; a11y, responsive, empty/error states.
- **Phase 4 (optional, Approach C)**: live crew stage/token streaming, NATS→SSE ingest feed, pdf.js real page render.

## 6. Task Breakdown

| # | Task | Layer | Depends on | Complexity |
|---|---|---|---|---|
| 1 | Bundle IBM Plex fonts locally; rewrite `globals.css` tokens/palette; nav shell | Frontend | — | Low |
| 2 | Rebuild landing page (1d) | Frontend | 1 | Low |
| 3 | `Catalog.list_kb()` + Gateway `GET /kb`; test | Backend | — | Low |
| 4 | `KbSelector` component; wire chat/ingest to it (drop raw paste) | Frontend | 1,3 | Low |
| 5 | Chat state → `turns[]`, multi-turn thread + composer | Frontend | 1 | Medium |
| 6 | Surface Critic `ungrounded_claims` in refusal payload (contract + crew + gateway); regen contracts; test | Backend | — | Medium |
| 7 | `AgentPipeline` component; emit a `status` event per crew stage (Planner/Retriever/Critic/Synthesizer) incl. `blocked`; extend SSE handlers | Backend+Frontend | 5 | Medium |
| 8 | `Catalog.get_chunk()` + Gateway `GET /chunks/{id}`; test | Backend | — | Low |
| 9 | `SourceInspector` (extends `CitationPanel`): lift selected-citation to page; schematic highlight w/ real page dims; optional chunk text | Frontend | 5,8 | Medium |
| 10 | `RefusalCard` (verdict + suggested-query chips) | Frontend | 6 | Low |
| 11 | Per-stage saga status: additive `progress`/`stages` on document + `GET /documents/{id}/progress` (or widen status feed); publish chunk/graph/vector stages; test | Backend | — | Medium |
| 12 | Widen `GET /documents/{id}` with provenance fields | Backend | — | Low |
| 13 | `SagaStepper` + live counts; wire polling/feed | Frontend | 11,12 | Medium |
| 14 | Confirm-with-override: extend `POST /documents/{id}/confirm` to accept `domain_id`; saga resume honors it; test | Backend | — | Medium |
| 15 | `DomainConfirmCard` (Confirm / Change) | Frontend | 13,14 | Low |
| 16 | **Multi-KB (§0.4):** `QueryRequest.kb_ids[]` (alias `kb_id`) through gateway `/query`+`/query/stream`, query_agent `/answer`+`/retrieve`, Planner scope (R29), `retrieval.retrieve()` fan-out; test single-KB parity + cross-KB scoping | Backend | 3 | Large |
| 17 | **Per-answer subgraph (§0.5):** add `EvidenceSet.subgraph{nodes,edges}`; graph `/expand` returns names/types/edges; crew populates it; regen contracts; test | Backend | — | Medium |
| 18 | Upgrade `EntityGraph` to named/typed nodes + edges from `evidence.subgraph` | Frontend | 17 | Medium |
| 19 | **Live pipeline (§0.3):** query_agent `/answer/stream` (SSE) emitting per-stage events + streamed synthesizer tokens; gateway proxies through to browser SSE (replace the fake word-split); keep answer identical; re-run eval gate | Backend | 7,16 | XL |
| 20 | **Live ingest feed (§0.3):** gateway `GET /documents/{id}/events` (SSE) forwarding NATS `ingest.status`; ingest page consumes it (drop the 40× poll loop) | Backend+Frontend | 11,13 | Large |
| 21 | Add Vitest + Testing Library; component tests for 4,7,9,10,13,15,18 + streaming handlers | Frontend/Test | above | Medium |
| 22 | A11y pass (roles/aria on pipeline & stepper), empty/error/loading states, responsive check | Frontend | Phase 0–3 | Medium |

## 7. Rollback & Migration Strategy
- **Data migration**: none for A/B if per-stage status is additive (new `progress` field/store; keep `document.status`). If a `progress` column is added, it is nullable/backward-compatible — old docs simply have no per-stage detail.
- **API migration**: all new endpoints are additive; existing `/kb`, `/documents/{id}`, `/query/stream` keep working. Widening `GET /documents/{id}` and adding a `verdict`/ungrounded field are additive (consumers ignore unknown fields). Contract regen (N9) must be committed together.
- **Rollback**: revert the web build to restore the old three pages; drop unused routes. No irreversible state. Consider a feature flag (`NEXT_PUBLIC_UI_V2`) to toggle old/new FE during rollout.

## 8. Post-Deployment Monitoring
| Metric | Method | Target | Alert |
|---|---|---|---|
| Chat error-event rate | SSE `error` events / queries | < 1% | > 5% |
| KB-list / chunk-fetch p95 latency | Gateway timing | < 150ms | > 500ms |
| Ingest stepper "stuck" rate | docs in a non-terminal stage > N min | ~0 | any sustained |
| Over-refusal (guard) | existing eval answerable cohort (R71) | ≥ 0.90 | < 0.85 |
- **Signals**: positive — citations click through to correct spans, refusals show verdicts; negative — blank inspector, pipeline stuck on a stage, KB list empty. Leading — rising SSE `error` events.

## 9. Open Questions

**Resolved in review (§0):** (1) schematic inspector, (2) in-tab history, (3) live
pipeline now, (4) multi-KB `kb_ids[]`, (5) per-answer subgraph.

**Newly surfaced by the locked decisions — resolve before build:**
1. **Eval gate under multi-KB** — the golden set is single-KB. Confirm the gate is
   re-run with `kb_ids=[one]` as the parity baseline, and decide whether any
   multi-KB golden cases are added. Retrieval fan-out must not change single-KB scores.
2. **Synthesizer token streaming feasibility** — real token streaming (Task 19)
   requires the Synthesizer/Model to stream from the LLM; `synthesize()` currently
   returns a complete `Answer`. If the model path can't stream tokens, fall back to
   server-side chunking of the *final* text (still real stage events) — confirm which.
3. **`kb_id` alias lifetime** — how long do we dual-accept legacy `kb_id` before
   removing it? (Pre-1.0 internal app → likely one release.)
4. **Cross-KB provenance/domain mismatch** — if selected KBs have different pinned
   domains (R2), does the Planner/Synthesizer handle mixed schemas, or do we
   constrain multi-select to same-domain KBs for v1?
