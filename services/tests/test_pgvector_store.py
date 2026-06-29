"""pgvector adapter test (R20/R21) — runs only against a real pgvector DB.

Set PGVECTOR_TEST_DSN (e.g. a pgvector/pgvector container) to run; skipped otherwise.
"""

from __future__ import annotations

import os

import pytest
from provenance_contracts import VectorRecord, VectorStorePort
from provenance_services.embedder import DeterministicEmbedder
from provenance_services.pgvector_store import PgVectorStore

DSN = os.environ.get("PGVECTOR_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set PGVECTOR_TEST_DSN to run pgvector tests")


def test_satisfies_vector_store_port() -> None:
    assert isinstance(PgVectorStore(DSN or ""), VectorStorePort)


@pytest.mark.asyncio
async def test_upsert_query_and_isolation() -> None:
    emb = DeterministicEmbedder(dim=64)
    store = PgVectorStore(DSN or "")

    def rec(cid: str, text: str) -> VectorRecord:
        return VectorRecord(chunk_id=cid, embedding=emb.embed([text])[0], text=text)

    try:
        await store.upsert("kbX", [rec("c1", "apple revenue"), rec("c2", "banana bread")])
        await store.upsert("kbY", [rec("d1", "other")])
        hits = await store.query("kbX", emb.embed(["apple revenue"])[0], k=2)
        assert hits[0].chunk_id == "c1"
        all_x = await store.query("kbX", emb.embed(["x"])[0], k=10)
        assert {h.chunk_id for h in all_x} == {"c1", "c2"}  # KB isolation (R4)
    finally:
        await store.close()
