"""Pre-implementation (RED) tests for the UI-redesign ingestion surface.

Maps to spec.md: R-BE-6 (per-stage saga progress), R-BE-8 (confirm-with-override).
Style matches test_ingestion.py (pure helpers / monkeypatch, no network).
These FAIL until the features exist.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from provenance_services import gateway, ingestion

client = TestClient(gateway.app)


# --------------------------------------------------- R-BE-6 · per-stage saga progress
def test_ingestion_declares_all_seven_saga_stages() -> None:
    """The saga must expose per-stage progress for all seven stages, including chunk /
    write_graph / vector that are silent today. A canonical STAGES vocabulary is the
    contract the SagaStepper renders."""
    stages = getattr(ingestion, "STAGES", None)  # red until added
    assert stages is not None
    for stage in ("parse", "chunk", "detect", "extract", "graph", "embed", "vector"):
        assert stage in stages


@pytest.mark.asyncio
async def test_status_event_with_stage_progress_is_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A structured per-stage progress event must reach the catalog so the UI feed can show
    which stage is active (not just a single coarse status string)."""
    recorded: dict = {}

    async def fake_record_progress(doc_id, stage, state):  # type: ignore[no-untyped-def]
        recorded.update(doc=doc_id, stage=stage, state=state)

    monkeypatch.setattr(gateway.catalog, "record_progress", fake_record_progress, raising=False)
    evt = json.dumps({"document_id": "d1", "status": "extracting",
                      "stage": "extract", "state": "active"}).encode()
    await gateway._on_status(evt, {})
    assert recorded.get("stage") == "extract"  # red until _on_status routes stage progress


# ----------------------------------------------------- R-BE-8 · confirm-with-override
def test_confirm_endpoint_forwards_domain_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /documents/{id}/confirm must forward an optional domain override so the user's
    'Change' choice reaches the saga (R55/R9)."""
    published: list[dict] = []

    async def fake_publish(subject, data):  # type: ignore[no-untyped-def]
        published.append(json.loads(data))

    monkeypatch.setattr(gateway.bus, "publish", fake_publish)
    r = client.post("/documents/d1/confirm", json={"domain_id": "legal_contracts"})
    assert r.status_code == 200
    assert published and published[0].get("domain_id") == "legal_contracts"  # red: body ignored today


@pytest.mark.asyncio
async def test_confirm_resume_records_domain_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """A resumed job carrying a domain override must run the saga with that domain pinned,
    not the low-confidence detection (R55)."""
    resumed: list[dict] = []

    async def fake_run(data, headers):  # type: ignore[no-untyped-def]
        resumed.append(json.loads(data))

    monkeypatch.setattr(ingestion, "_run_saga", fake_run)
    ingestion._paused_jobs["d9"] = {"document_id": "d9", "kb_id": "kb1", "content_b64": "x"}

    await ingestion._on_confirm(b'{"document_id": "d9", "domain_id": "legal_contracts"}', {})
    assert resumed and resumed[0]["confirmed"] is True
    assert resumed[0].get("domain_id") == "legal_contracts"  # red until override threaded
