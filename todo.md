# TODO — Provenance UI Redesign

Live task checklist for `spec.md`. Check items off as completed. Group = phase.
Each task notes its layer, dependencies, and the requirement(s) it satisfies.

## Phase 0 — Foundation
- [ ] **T1** Bundle IBM Plex (Sans/Serif/Mono) locally; rewrite `web/app/globals.css` tokens to the mockup palette (`#5e8bff`/`#35c990`/`#f0a83a`); nav shell. — FE — *R-UI-9 setup*
- [x] **T2** Rebuild landing page `web/app/page.tsx` (hero + answer→source visual). — FE — deps: T1 — *R-UI-9*
- [x] **T3** `Catalog.list_kb()` + gateway `GET /kb`; test. — BE — *R-BE-1* ✅ green
- [x] **T4** Multi-KB query path: `QueryRequest.kb_ids[]` (alias `kb_id`) through gateway `/query`+`/query/stream`, query_agent `/answer`+`/retrieve`, `run_crew`, `retrieval.retrieve()` fan-out+union; regen contracts; parity + cross-KB tests; **re-run eval gate**. — BE — deps: T3 — *R-BE-2* ⚠️ eval-sensitive ✅ green (parity + eval gate re-run)
- [x] **T5** `KbSelector` (multi-select) component; wire chat + ingest to it (drop raw paste). — FE — deps: T1,T3,T4 — *R-UI-1*
- [x] **T6** Chat state → `turns[]`; multi-turn thread + composer; lift selected-citation to page level. — FE — deps: T1 — *R-UI-7*

## Phase 1 — Provenance chat (1a / 1b)
- [x] **T7** Surface Critic `ungrounded_claims` on the refusal payload (extend `Answer`); crew + gateway; regen contracts; test. — BE — *R-BE-3* ✅ green
- [x] **T8** Live crew streaming: query_agent `/answer/stream` (SSE) emitting `planner|retriever|critic|synthesizer` stage events + **post-`ok`** answer tokens; gateway proxies through (replace fake word-split); **answer-bytes parity** test. — BE — deps: T4,T7 — *R-BE-4* ⚠️ enforces R31/R32 ✅ green (byte-parity + eval gate re-run)
- [x] **T9** `AgentPipeline` component (4 stages, active/done/blocked) + streamed-token rendering; extend `lib/api.ts` SSE handlers for named stages. — FE — deps: T6,T8 — *R-UI-2*
- [x] **T10** `Catalog.get_chunk()` + gateway `GET /chunks/{id}`; test. — BE — *R-BE-5* ✅ green
- [x] **T11** `SourceInspector` (extends `CitationPanel`): schematic bbox highlight w/ real page dims; optional chunk text from T10. — FE — deps: T6,T10 — *R-UI-3*
- [x] **T12** `RefusalCard` (verdict + ungrounded claim + suggested-query chips). — FE — deps: T7 — *R-UI-4*

## Phase 2 — Ingestion saga (1c)
- [x] **T13** Per-stage saga status: additive `progress[{stage,state,detail}]` on document; publish silent chunk/graph/vector stages; keep `document.status` string; test. — BE — *R-BE-6*
- [x] **T14** Live ingest feed: gateway `GET /documents/{id}/events` (SSE) forwarding NATS `ingest.status`; test. — BE — deps: T13 — *R-BE-7* ✅ green
- [ ] **T15** Widen `GET /documents/{id}` with provenance fields (detected_domain, confidence, parse_method, ocr_engine, trace_id). — BE — *R-BE-10*
- [ ] **T16** `SagaStepper` + live counts; consume T14 SSE (drop 40× poll loop in `web/app/ingest/page.tsx`). — FE — deps: T13,T14,T15 — *R-UI-5*
- [x] **T17** Confirm-with-override: extend `POST /documents/{id}/confirm` with optional `domain_id`/`schema_version`; saga resumes honoring + records it; test. — BE — *R-BE-8* ✅ green
- [ ] **T18** `DomainConfirmCard` (Confirm / Change). — FE — deps: T16,T17 — *R-UI-6*

## Phase 3 — Graph + polish
- [x] **T19** Per-answer subgraph (contract + retrieval populate + crew merge done; graph `/expand` real names/types deferred — see decisions log): `EvidenceSet.subgraph{nodes,edges}`; graph `/expand` returns names/types/edges; crew populates; regen contracts; test. — BE — *R-BE-9*
- [x] **T20** Upgrade `EntityGraph` to named/typed nodes + edges from `evidence.subgraph`. — FE — deps: T19 — *R-UI-8*
- [ ] **T21** Add Vitest + Testing Library; component tests for T2,T5,T9,T11,T12,T16,T18,T20 + streaming handlers. — FE/Test — deps: above
- [ ] **T22** A11y pass (roles/aria on pipeline + stepper), empty/error/loading states, responsive check. — FE — deps: Phase 0–3

## Cross-cutting gates (must stay green every PR)
- [ ] Contract drift check (`python scripts/gen_ts_contracts.py`, N9) after any contract change (T4,T7,T8,T19).
- [ ] Eval gate (`eval/tests/test_gate.py`) green — especially after T4/T8 (answer-bytes parity).
- [ ] License-audit green (fonts OFL, optional react-force-graph MIT, dev Vitest MIT).
- [ ] `ruff` + `mypy` (services) · `eslint` + `tsc` (web).

## Progress log
- Red state established: 17 backend tests + 9 web test files (Vitest harness added). Existing 41 services tests green.
- Slice 1 (commit): R-BE-1 (GET /kb + list_kb), R-BE-3 (Answer.ungrounded_claims + crew), R-BE-5 (GET /chunks + get_chunk), R-BE-9 contract (Subgraph model + EvidenceSet.subgraph). Contracts regenerated (N9 drift gate green).
- Slice 7 (commit): Frontend components green — landing (R-UI-9), KbSelector (R-UI-1), AgentPipeline (R-UI-2), SourceInspector (R-UI-3), RefusalCard (R-UI-4), SagaStepper (R-UI-5), DomainConfirmCard (R-UI-6), multi-turn ChatPage (R-UI-7), EntityGraph subgraph (R-UI-8). All 9 Vitest files pass (11 tests); tsc+eslint clean.
- Slice 6 (commit): R-BE-9 populate (retrieval builds provenance subgraph nodes+expands_to edges; query_agent /answer merges per-subquery subgraphs). ALL backend reds green — 146 passed.
- Slice 5 (commit): R-BE-6 (STAGES vocab + saga on_step per-stage publish + catalog.record_progress + gateway routing) & R-BE-7 (in-process SSE fan-out at /documents/{id}/events; snapshot+terminal close).
- Slice 4 (commit): R-BE-4 (gateway-edge live streaming: 4 stage events + post-critic verified tokens; byte-parity + eval gate 22 green).
- Slice 3 (commit): R-BE-2 (multi-KB kb_ids fan-out; kb_ids=[one] byte-identical to kb_id — eval gate 22 green).
- Slice 2 (commit): R-BE-8 (confirm-with-override: gateway body + ingestion resume + detect honors override).
- Status: services suite 113 passed / 11 UI-red remaining / 0 regressions; ruff clean.
- Remaining backend reds: R-BE-2 (multi-KB thread ⚠ eval-sensitive), R-BE-4 (live streaming ⚠ eval-sensitive), R-BE-6 (saga per-stage), R-BE-7 (ingest SSE route), R-BE-9 populate. Plus all 9 web component builds (T2,T5,T6,T9,T11,T12,T13,T15,T16,T18,T20).

## Decisions log
- [2026-07-07] R-BE-4 live streaming orchestrated at the **gateway edge** (`/query/stream`),
  not a separate query_agent `/answer/stream` proxy. The RED acceptance tests patch
  `gateway.call` and assert on the gateway SSE body; R53 keeps crew execution as one verified
  call in query_agent; and edge-orchestration makes "no unverified token reaches the browser"
  true *by construction* — the gateway only ever chunks text that `/answer` already verified
  through the Critic. Answer bytes preserved via `\S+\s*` chunking. spec.md R-BE-4 updated.
- [2026-07-07] R-BE-9 subgraph populated at the **retrieval layer** from the graph-lift id
  lists (nodes = linked+expanded entities, edges = linked→expanded `expands_to`). Node names
  fall back to entity ids and type to a generic `entity` because the RED acceptance test's
  RetrievalDeps.link/expand return `list[str]` — the retrieval contract is id-based. Real
  canonical names + entity types + relation labels require enriching the Graph service
  `/link` + `/expand` responses (a cross-service contract change with eval-gate risk, not
  covered by the current test); tracked as a T19/T20 follow-up. Structure is stable now, so
  the frontend EntityGraph (T20) can build against it and richer labels drop in later.
