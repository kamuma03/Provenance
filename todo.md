# TODO — Provenance UI Redesign

Live task checklist for `spec.md`. Check items off as completed. Group = phase.
Each task notes its layer, dependencies, and the requirement(s) it satisfies.

## Phase 0 — Foundation
- [ ] **T1** Bundle IBM Plex (Sans/Serif/Mono) locally; rewrite `web/app/globals.css` tokens to the mockup palette (`#5e8bff`/`#35c990`/`#f0a83a`); nav shell. — FE — *R-UI-9 setup*
- [ ] **T2** Rebuild landing page `web/app/page.tsx` (hero + answer→source visual). — FE — deps: T1 — *R-UI-9*
- [ ] **T3** `Catalog.list_kb()` + gateway `GET /kb`; test. — BE — *R-BE-1*
- [ ] **T4** Multi-KB query path: `QueryRequest.kb_ids[]` (alias `kb_id`) through gateway `/query`+`/query/stream`, query_agent `/answer`+`/retrieve`, `run_crew`, `retrieval.retrieve()` fan-out+union; regen contracts; parity + cross-KB tests; **re-run eval gate**. — BE — deps: T3 — *R-BE-2* ⚠️ eval-sensitive
- [ ] **T5** `KbSelector` (multi-select) component; wire chat + ingest to it (drop raw paste). — FE — deps: T1,T3,T4 — *R-UI-1*
- [ ] **T6** Chat state → `turns[]`; multi-turn thread + composer; lift selected-citation to page level. — FE — deps: T1 — *R-UI-7*

## Phase 1 — Provenance chat (1a / 1b)
- [ ] **T7** Surface Critic `ungrounded_claims` on the refusal payload (extend `Answer`); crew + gateway; regen contracts; test. — BE — *R-BE-3*
- [ ] **T8** Live crew streaming: query_agent `/answer/stream` (SSE) emitting `planner|retriever|critic|synthesizer` stage events + **post-`ok`** answer tokens; gateway proxies through (replace fake word-split); **answer-bytes parity** test. — BE — deps: T4,T7 — *R-BE-4* ⚠️ enforces R31/R32: no pre-verification tokens
- [ ] **T9** `AgentPipeline` component (4 stages, active/done/blocked) + streamed-token rendering; extend `lib/api.ts` SSE handlers for named stages. — FE — deps: T6,T8 — *R-UI-2*
- [ ] **T10** `Catalog.get_chunk()` + gateway `GET /chunks/{id}`; test. — BE — *R-BE-5*
- [ ] **T11** `SourceInspector` (extends `CitationPanel`): schematic bbox highlight w/ real page dims; optional chunk text from T10. — FE — deps: T6,T10 — *R-UI-3*
- [ ] **T12** `RefusalCard` (verdict + ungrounded claim + suggested-query chips). — FE — deps: T7 — *R-UI-4*

## Phase 2 — Ingestion saga (1c)
- [ ] **T13** Per-stage saga status: additive `progress[{stage,state,detail}]` on document; publish silent chunk/graph/vector stages; keep `document.status` string; test. — BE — *R-BE-6*
- [ ] **T14** Live ingest feed: gateway `GET /documents/{id}/events` (SSE) forwarding NATS `ingest.status`; test. — BE — deps: T13 — *R-BE-7*
- [ ] **T15** Widen `GET /documents/{id}` with provenance fields (detected_domain, confidence, parse_method, ocr_engine, trace_id). — BE — *R-BE-10*
- [ ] **T16** `SagaStepper` + live counts; consume T14 SSE (drop 40× poll loop in `web/app/ingest/page.tsx`). — FE — deps: T13,T14,T15 — *R-UI-5*
- [ ] **T17** Confirm-with-override: extend `POST /documents/{id}/confirm` with optional `domain_id`/`schema_version`; saga resumes honoring + records it; test. — BE — *R-BE-8*
- [ ] **T18** `DomainConfirmCard` (Confirm / Change). — FE — deps: T16,T17 — *R-UI-6*

## Phase 3 — Graph + polish
- [ ] **T19** Per-answer subgraph: `EvidenceSet.subgraph{nodes,edges}`; graph `/expand` returns names/types/edges; crew populates; regen contracts; test. — BE — *R-BE-9*
- [ ] **T20** Upgrade `EntityGraph` to named/typed nodes + edges from `evidence.subgraph`. — FE — deps: T19 — *R-UI-8*
- [ ] **T21** Add Vitest + Testing Library; component tests for T2,T5,T9,T11,T12,T16,T18,T20 + streaming handlers. — FE/Test — deps: above
- [ ] **T22** A11y pass (roles/aria on pipeline + stepper), empty/error/loading states, responsive check. — FE — deps: Phase 0–3

## Cross-cutting gates (must stay green every PR)
- [ ] Contract drift check (`python scripts/gen_ts_contracts.py`, N9) after any contract change (T4,T7,T8,T19).
- [ ] Eval gate (`eval/tests/test_gate.py`) green — especially after T4/T8 (answer-bytes parity).
- [ ] License-audit green (fonts OFL, optional react-force-graph MIT, dev Vitest MIT).
- [ ] `ruff` + `mypy` (services) · `eslint` + `tsc` (web).
