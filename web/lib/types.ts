// Cross-service types are GENERATED from the Pydantic contracts (single source of truth, N9)
// — never hand-copied. Regenerate with `python scripts/gen_ts_contracts.py`; CI checks drift.
import type { Answer, EvidenceSet } from "./contracts.gen";

export type {
  Answer,
  BBox,
  Citation,
  Claim,
  ScoredChunk,
  Subgraph,
  SubgraphEdge,
  SubgraphNode,
} from "./contracts.gen";

// The UI's name for the retriever's EvidenceSet.
export type Evidence = EvidenceSet;

// ---- web-only types (not cross-service contracts) ----

// A knowledge base as returned by GET /kb (R-BE-1) — surfaced by the KbSelector (R-UI-1).
export interface Kb {
  id: string;
  name: string;
  domain_id: string;
  created_at: string;
}

// One node of the crew pipeline / ingestion saga stepper (R-UI-2 / R-UI-5). `state` is the
// only vocabulary the UI renders and must reflect what the backend actually reported
// (truthful UI): `pending`, `active`, `done`, `blocked` (Critic refusal / saga pause), `failed`.
export type StageState = "pending" | "active" | "done" | "blocked" | "failed";
export interface StageView {
  name: string;
  state: StageState;
  detail?: string;
}

// A live crew stage event off the SSE stream (R-BE-4): stage + state, plus the Critic's
// verdict / ungrounded claims on the `critic` stage.
export interface StageEvent {
  stage: string;
  state: StageState;
  verdict?: string;
  ungrounded_claims?: string[];
}

export interface StreamHandlers {
  onStatus?: (phase: string) => void;
  onStage?: (evt: StageEvent) => void;
  onToken?: (text: string) => void;
  onDone?: (answer: Answer, evidence: Evidence) => void;
  onError?: (err: unknown) => void;
  signal?: AbortSignal;
}

export const DOMAINS = [
  "generic",
  "sec_financial",
  "research_papers",
  "legal_contracts",
  "technical_software",
  "biomedical_clinical",
  "regulatory_standards",
  "patents",
] as const;

export type ProcessingTier = "quick" | "full";
