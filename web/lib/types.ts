export interface BBox {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  page_width?: number | null;
  page_height?: number | null;
}

export interface Citation {
  chunk_id: string;
  page: number;
  bbox: BBox;
}

export interface Claim {
  text: string;
  citations: Citation[];
  grounded: boolean | null;
}

export interface Answer {
  text: string;
  claims: Claim[];
  refused: boolean;
  refusal_reason: string | null;
}

export interface ScoredChunk {
  chunk_id: string;
  text: string;
  page: number;
  bbox: BBox;
  score: number;
}

export interface Evidence {
  subquery: string;
  chunks: ScoredChunk[];
  entity_ids: string[];
  graph_expanded: boolean;
}

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
