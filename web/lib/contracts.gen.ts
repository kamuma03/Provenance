// AUTO-GENERATED from packages/contracts (provenance_contracts) — do NOT edit by hand.
// Regenerate: python scripts/gen_ts_contracts.py  (CI checks this is up to date, N9).

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

export interface ScoredChunk {
  chunk_id: string;
  text: string;
  page: number;
  bbox: BBox;
  score: number;
}

export interface Claim {
  text: string;
  citations?: Citation[];
  grounded?: boolean | null;
}

export interface Answer {
  text: string;
  claims?: Claim[];
  refused?: boolean;
  refusal_reason?: string | null;
}

export interface EvidenceSet {
  subquery: string;
  chunks?: ScoredChunk[];
  entity_ids?: string[];
  graph_expanded?: boolean;
}
