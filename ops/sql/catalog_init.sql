-- Catalog schema (Postgres) — owned by the Gateway service (R52).
-- Applied at container init. KB / Document / Chunk metadata + provenance + trace_id.

CREATE TABLE IF NOT EXISTS knowledge_base (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    domain_id   TEXT NOT NULL,              -- pinned on creation (R2)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document (
    id                    TEXT PRIMARY KEY,
    kb_id                 TEXT NOT NULL REFERENCES knowledge_base(id),
    source                TEXT NOT NULL,
    content_type          TEXT NOT NULL,
    content_hash          TEXT NOT NULL,     -- idempotency key (N5)
    tier                  TEXT NOT NULL DEFAULT 'full',
    -- Constrain status to the saga's lifecycle values so a typo'd status is rejected at write
    -- time instead of leaving the UI polling forever (review L-9).
    status                TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'parsing', 'detecting', 'extracting', 'embedding',
                          'done', 'failed', 'awaiting_confirm')),
    -- provenance of how the document was processed (R11, R63)
    detected_domain       TEXT,
    detection_confidence  REAL,
    schema_version        TEXT,
    schema_stale          BOOLEAN NOT NULL DEFAULT FALSE,   -- R70
    parse_method          TEXT,              -- text_layer | ocr (R63)
    ocr_engine            TEXT,
    trace_id              TEXT,              -- correlates to the ingestion trace (R56)
    -- per-stage saga progress for the ingestion stepper (R-BE-6): {stage: state}, additive
    -- and separate from the coarse `status` lifecycle above.
    progress              JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- de-dupe identical content within a KB (N5)
    UNIQUE (kb_id, content_hash)
);

-- Chunk geometry lives in the Vector store's per-record metadata (bbox) and the Graph,
-- which own retrieval and provenance — a catalog `chunk` table would be write-only dead
-- schema, so it is intentionally not modelled here (review H-9). Reinstate only if the
-- Gateway itself needs to serve chunks.

-- Idempotent upgrade path for an already-provisioned catalog (the CREATE TABLE above only
-- fires on a fresh DB): add the per-stage progress column if a prior version lacks it.
ALTER TABLE document ADD COLUMN IF NOT EXISTS progress JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_document_kb ON document(kb_id);
