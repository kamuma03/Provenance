"""Service-to-service call helpers (HTTP + trace propagation).

Base URLs come from the environment (compose service names by default). The traced
client propagates the W3C trace context so a call shows up in the same trace (R56).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, cast

import httpx
from provenance_service import traced_client

log = logging.getLogger("clients")

SERVICE_URLS: dict[str, str] = {
    "parse": os.environ.get("PARSE_URL", "http://parse:8000"),
    "extraction": os.environ.get("EXTRACTION_URL", "http://extraction:8000"),
    "vector": os.environ.get("VECTOR_URL", "http://vector:8000"),
    "graph": os.environ.get("GRAPH_URL", "http://graph:8000"),
    "model": os.environ.get("MODEL_URL", "http://model:8000"),
    "query": os.environ.get("QUERY_URL", "http://query-agent:8000"),
    "gateway": os.environ.get("GATEWAY_URL", "http://gateway:8000"),
}

# Inter-service calls fan out to LLM-bearing endpoints (detect/extract, and the agentic
# /answer path: planner + critic + synthesizer). Cold model loads and multi-step generation
# legitimately exceed the default HTTP timeout, so it's configurable and defaults high.
_CALL_TIMEOUT_S = float(os.environ.get("SERVICE_CALL_TIMEOUT_S", "180"))
# Retry transient transport failures (connection refused / reset while a peer restarts). Only
# TransportError is retried — never an HTTP status — so a request that reached the server and
# may have side-effected isn't replayed (review L-4). All inter-service endpoints here are
# idempotent (MERGE/upsert/pure reads), so a connect-time retry is safe.
_CALL_RETRIES = int(os.environ.get("SERVICE_CALL_RETRIES", "2"))


async def _request(
    method: str, service: str, path: str, payload: dict[str, Any] | None
) -> dict[str, Any]:
    base = SERVICE_URLS[service]
    url = f"{base}{path}"
    last_exc: Exception | None = None
    for attempt in range(_CALL_RETRIES + 1):
        try:
            async with traced_client(_CALL_TIMEOUT_S) as client:
                resp = (
                    await client.post(url, json=payload or {})
                    if method == "POST"
                    else await client.get(url)
                )
                resp.raise_for_status()
                return cast("dict[str, Any]", resp.json())
        except httpx.TransportError as exc:
            last_exc = exc
            if attempt < _CALL_RETRIES:
                log.warning("%s %s failed (%s); retry %d/%d", method, url, exc,
                            attempt + 1, _CALL_RETRIES)
                await asyncio.sleep(0.2 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


async def call(service: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST to another service and return its JSON. Retries transient transport errors."""
    return await _request("POST", service, path, payload)


async def call_get(service: str, path: str) -> dict[str, Any]:
    """GET from another service and return its JSON. Retries transient transport errors."""
    return await _request("GET", service, path, None)
