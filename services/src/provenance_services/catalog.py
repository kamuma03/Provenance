"""Catalog repository — Postgres-backed KB/Document store owned by the Gateway (R52).

Minimal P0 surface: create a KB, create a Document in `queued` state. Schema is applied
by the Postgres init script (ops/sql/catalog_init.sql). Degrades gracefully if the DB is
unavailable (N6) so the skeleton flow still demonstrates the trace.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import asyncpg


def _dsn() -> str:
    return (
        f"postgresql://{os.environ.get('POSTGRES_USER', 'provenance')}:"
        f"{os.environ.get('POSTGRES_PASSWORD', 'change-me')}@"
        f"{os.environ.get('POSTGRES_HOST', 'postgres')}:"
        f"{os.environ.get('POSTGRES_PORT', '5432')}/"
        f"{os.environ.get('POSTGRES_DB', 'provenance')}"
    )


class Catalog:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        await self._ensure()

    async def _ensure(self) -> None:
        """(Re)establish the pool on demand. Startup may race Postgres readiness (the gateway
        can boot first), so instead of failing permanently we lazily reconnect on the next
        call once the DB is up — the skeleton still degrades gracefully if it never is (N6)."""
        if self._pool is not None:
            return
        try:
            self._pool = await asyncpg.create_pool(_dsn(), min_size=1, max_size=5)
        except Exception:  # pragma: no cover - DB not ready yet; retry on the next call
            self._pool = None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()

    async def ready(self) -> bool:
        await self._ensure()
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:  # pragma: no cover
            return False

    async def create_kb(self, kb_id: str, name: str, domain_id: str) -> None:
        await self._ensure()
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO knowledge_base (id, name, domain_id, created_at) "
                "VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO NOTHING",
                kb_id, name, domain_id, datetime.now(UTC),
            )

    async def create_document(
        self, doc_id: str, kb_id: str, source: str, content_type: str, content_hash: str
    ) -> tuple[str, bool] | None:
        """Insert a queued Document idempotently (N5).

        Returns ``(effective_id, created)``: on a duplicate ``(kb_id, content_hash)`` the
        row is not re-inserted and ``effective_id`` is the *existing* document's id with
        ``created=False`` — so the caller can return that id and skip re-running the saga
        instead of minting a dangling id (review H-4). ``None`` when the DB is unavailable.
        """
        await self._ensure()
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO document (id, kb_id, source, content_type, content_hash, status) "
                "VALUES ($1, $2, $3, $4, $5, 'queued') "
                "ON CONFLICT (kb_id, content_hash) DO NOTHING RETURNING id",
                doc_id, kb_id, source, content_type, content_hash,
            )
            if row is not None:
                return doc_id, True
            existing = await conn.fetchrow(
                "SELECT id FROM document WHERE kb_id = $1 AND content_hash = $2",
                kb_id, content_hash,
            )
            return (str(existing["id"]), False) if existing else (doc_id, True)

    async def update_status(self, doc_id: str, status: str) -> None:
        await self._ensure()
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE document SET status = $2 WHERE id = $1", doc_id, status)

    async def record_provenance(
        self, doc_id: str, status: str, provenance: dict[str, object]
    ) -> None:
        """Persist the terminal status plus how the document was processed — domain,
        confidence, schema version, parse method, OCR engine, and the correlating
        trace_id (R56's acceptance criterion, review H-9)."""
        await self._ensure()
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE document SET status = $2, detected_domain = $3, "
                "detection_confidence = $4, schema_version = $5, parse_method = $6, "
                "ocr_engine = $7, trace_id = $8 WHERE id = $1",
                doc_id, status,
                provenance.get("detected_domain"),
                provenance.get("detection_confidence"),
                provenance.get("schema_version"),
                provenance.get("parse_method"),
                provenance.get("ocr_engine"),
                provenance.get("trace_id"),
            )

    async def get_document(self, doc_id: str) -> dict[str, str] | None:
        await self._ensure()
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, kb_id, source, status FROM document WHERE id = $1", doc_id
            )
            return dict(row) if row else None
