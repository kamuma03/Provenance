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
    status                TEXT NOT NULL DEFAULT 'queued',
    -- provenance of how the document was processed (R11, R63)
    detected_domain       TEXT,
    detection_confidence  REAL,
    schema_version        TEXT,
    schema_stale          BOOLEAN NOT NULL DEFAULT FALSE,   -- R70
    parse_method          TEXT,              -- text_layer | ocr (R63)
    ocr_engine            TEXT,
    trace_id              TEXT,              -- correlates to the ingestion trace (R56)
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- de-dupe identical content within a KB (N5)
    UNIQUE (kb_id, content_hash)
);

CREATE TABLE IF NOT EXISTS chunk (
    id             TEXT PRIMARY KEY,
    document_id    TEXT NOT NULL REFERENCES document(id),
    kb_id          TEXT NOT NULL REFERENCES knowledge_base(id),
    text           TEXT NOT NULL,
    page           INTEGER NOT NULL,
    bbox           JSONB NOT NULL,           -- [x0,y0,x1,y1] for citation highlight (R6)
    reading_order  INTEGER NOT NULL,
    element_type   TEXT NOT NULL DEFAULT 'text'
);

CREATE INDEX IF NOT EXISTS idx_document_kb ON document(kb_id);
CREATE INDEX IF NOT EXISTS idx_chunk_document ON chunk(document_id);
