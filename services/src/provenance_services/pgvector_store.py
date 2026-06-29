"""pgvector adapter for the VectorStorePort (R20/R21) — the in-database backend.

Vectors live in Postgres (the same engine as the Catalog), namespace = kb_id column (R4).
Cosine distance via the `<=>` operator. Dense query; hybrid_query falls back to dense for
v1. This is the "minimize moving parts" option from the benchmark (Appendix C).
"""

from __future__ import annotations

import json

import asyncpg
from pgvector.asyncpg import register_vector
from provenance_contracts import QueryHit, VectorRecord


class PgVectorStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None
        self._dim: int | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            async def init(conn: asyncpg.Connection) -> None:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                await register_vector(conn)
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4, init=init)
        return self._pool

    async def _ensure_table(self, dim: int) -> None:
        self._dim = dim
        pool = await self._get_pool()
        await pool.execute(
            f"CREATE TABLE IF NOT EXISTS prov_vectors ("
            f"kb_id text, chunk_id text, embedding vector({dim}), "
            f"text text, metadata jsonb, PRIMARY KEY (kb_id, chunk_id))"
        )

    async def upsert(self, namespace: str, records: list[VectorRecord]) -> None:
        if not records:
            return
        await self._ensure_table(len(records[0].embedding))
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO prov_vectors (kb_id, chunk_id, embedding, text, metadata) "
                "VALUES ($1, $2, $3, $4, $5) "
                "ON CONFLICT (kb_id, chunk_id) DO UPDATE SET "
                "embedding = EXCLUDED.embedding, text = EXCLUDED.text, "
                "metadata = EXCLUDED.metadata",
                [
                    (namespace, r.chunk_id, r.embedding, r.text, json.dumps(r.metadata))
                    for r in records
                ],
            )

    async def query(
        self, namespace: str, vector: list[float], k: int, filter: dict[str, str] | None = None
    ) -> list[QueryHit]:
        pool = await self._get_pool()
        sql = (
            "SELECT chunk_id, text, metadata, 1 - (embedding <=> $1) AS score "
            "FROM prov_vectors WHERE kb_id = $2"
        )
        args: list[object] = [vector, namespace]
        if filter:
            sql += " AND metadata @> $3::jsonb"
            args.append(json.dumps(filter))
        sql += f" ORDER BY embedding <=> $1 LIMIT {int(k)}"
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [
            QueryHit(
                chunk_id=r["chunk_id"], score=float(r["score"]), text=r["text"] or "",
                metadata={k: str(v) for k, v in (json.loads(r["metadata"]) or {}).items()},
            )
            for r in rows
        ]

    async def hybrid_query(
        self, namespace: str, vector: list[float], text: str, k: int,
        filter: dict[str, str] | None = None,
    ) -> list[QueryHit]:
        return await self.query(namespace, vector, k, filter)  # dense for v1

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
