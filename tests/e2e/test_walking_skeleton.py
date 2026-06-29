"""Walking-skeleton end-to-end smoke test (P0 gate).

Codifies the manual verification: with the compose stack up, an upload flows through the
ingestion saga and a query fans out — both returning the expected skeleton responses.

Guarded by PROVENANCE_E2E=1 so unit CI (no compose) skips it. To run:

    cd ops && docker compose up -d
    PROVENANCE_E2E=1 GATEWAY_URL=http://localhost:8000 pytest tests/e2e -q
"""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PROVENANCE_E2E") != "1",
    reason="requires the compose stack (set PROVENANCE_E2E=1)",
)

BASE = os.environ.get("GATEWAY_URL", "http://localhost:8000")


def test_health() -> None:
    r = httpx.get(f"{BASE}/health", timeout=10)
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_upload_flow_returns_queued() -> None:
    kb = httpx.post(f"{BASE}/kb", json={"name": "Demo", "domain_id": "sec_financial"}, timeout=10)
    kb_id = kb.json()["id"]
    up = httpx.post(
        f"{BASE}/kb/{kb_id}/documents",
        json={"source": "demo.pdf", "content": "hello world"},
        timeout=10,
    )
    assert up.status_code == 202
    body = up.json()
    assert body["status"] == "queued" and body["document_id"].startswith("doc_")


def test_query_fans_out_and_returns_answer() -> None:
    r = httpx.post(f"{BASE}/query", json={"query": "risk factors?"}, timeout=15)
    assert r.status_code == 200
    answer = r.json()["answer"]
    assert "skeleton" in answer["text"].lower()
    assert answer["refused"] is False
