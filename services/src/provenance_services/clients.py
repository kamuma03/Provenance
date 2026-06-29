"""Service-to-service call helpers (HTTP + trace propagation).

Base URLs come from the environment (compose service names by default). The traced
client propagates the W3C trace context so a call shows up in the same trace (R56).
"""

from __future__ import annotations

import os
from typing import Any

from provenance_service import traced_client

SERVICE_URLS: dict[str, str] = {
    "parse": os.environ.get("PARSE_URL", "http://parse:8000"),
    "extraction": os.environ.get("EXTRACTION_URL", "http://extraction:8000"),
    "vector": os.environ.get("VECTOR_URL", "http://vector:8000"),
    "graph": os.environ.get("GRAPH_URL", "http://graph:8000"),
    "model": os.environ.get("MODEL_URL", "http://model:8000"),
    "query": os.environ.get("QUERY_URL", "http://query-agent:8000"),
}


async def call(service: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST to another service and return its JSON. Raises on transport/HTTP error."""
    base = SERVICE_URLS[service]
    async with traced_client() as client:
        resp = await client.post(f"{base}{path}", json=payload or {})
        resp.raise_for_status()
        return resp.json()


async def call_get(service: str, path: str) -> dict[str, Any]:
    """GET from another service and return its JSON."""
    base = SERVICE_URLS[service]
    async with traced_client() as client:
        resp = await client.get(f"{base}{path}")
        resp.raise_for_status()
        return resp.json()
