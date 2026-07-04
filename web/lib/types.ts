// Cross-service types are GENERATED from the Pydantic contracts (single source of truth, N9)
// — never hand-copied. Regenerate with `python scripts/gen_ts_contracts.py`; CI checks drift.
import type { Answer, EvidenceSet } from "./contracts.gen";

export type { Answer, BBox, Citation, Claim, ScoredChunk } from "./contracts.gen";

// The UI's name for the retriever's EvidenceSet.
export type Evidence = EvidenceSet;

// ---- web-only types (not cross-service contracts) ----
export interface StreamHandlers {
  onStatus?: (phase: string) => void;
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
