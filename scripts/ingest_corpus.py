"""Batch-ingest the corpus/ PDFs through the running stack (R5 saga).

Creates one KB per domain, uploads each PDF (base64) to POST /kb/{id}/documents,
and drives the saga to a terminal state by polling GET /documents/{id}. Uploads run
with a bounded in-flight window so the pipeline back-pressures instead of flooding
the bus. Idempotent: the gateway dedupes by content hash (N5), so re-runs resume.

A live status snapshot is written to --status-file after every poll cycle.

Usage:
    python scripts/ingest_corpus.py [--gateway http://localhost:8000]
        [--limit N] [--concurrency 12] [--status-file <path>]
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

TERMINAL = {"done", "failed"}

# Content is now stored out-of-band (gateway catalog) and fetched by id, so the old NATS
# payload limit no longer applies. This guard only rejects absurdly large uploads that would
# strain the gateway's in-memory base64 decode.
MAX_B64_BYTES = 400_000_000

# Corpus subtree -> (KB name, domain_id). Domain is auto-detected per doc regardless;
# this just groups documents into KBs and sets each KB's default domain.
KB_MAP = [
    ("corpora/sec_financial", "SEC Financial", "sec_financial"),
    ("corpora/research_papers", "Research Papers", "research_papers"),
]


def _req(method: str, url: str, payload: dict | None = None, timeout: int = 120) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"error": body[:200]}


def create_kb(gateway: str, name: str, domain_id: str) -> str:
    status, body = _req("POST", f"{gateway}/kb", {"name": name, "domain_id": domain_id})
    kb_id = body.get("id") or body.get("kb_id") or body.get("knowledge_base_id")
    if not kb_id:
        raise RuntimeError(f"KB create failed ({status}): {body}")
    return kb_id


def upload(gateway: str, kb_id: str, pdf: Path, domain_id: str | None = None) -> str | None | bool:
    content_b64 = base64.b64encode(pdf.read_bytes()).decode()
    if len(content_b64) > MAX_B64_BYTES:
        print(f"  skip {pdf.name}: base64 {len(content_b64)//10**6}MB exceeds NATS payload cap",
              file=sys.stderr)
        return False  # sentinel: too large to enqueue
    payload: dict = {"source": pdf.name, "content_b64": content_b64}
    if domain_id:
        payload["domain_id"] = domain_id  # pin the KB's known domain (skip auto-detect)
    status, body = _req("POST", f"{gateway}/kb/{kb_id}/documents", payload, timeout=300)
    if status in (200, 202):
        return body.get("document_id")
    print(f"  upload {pdf.name}: HTTP {status} {body}", file=sys.stderr)
    return None


def poll(gateway: str, doc_id: str) -> dict:
    status, body = _req("GET", f"{gateway}/documents/{doc_id}", timeout=30)
    return body if status == 200 else {"status": "unknown"}


def terminal_state(doc: dict) -> str | None:
    """Return 'done'/'failed' if the saga has reached a terminal state. The coarse `status`
    column can lag the actual saga (a lost final status event leaves it mid-stage), so treat
    the last saga stage (`vector`) reaching 'done' in the progress map as success too."""
    st = str(doc.get("status", "unknown"))
    if st == "failed":
        return "failed"
    if st == "done":
        return "done"
    progress = doc.get("progress") or {}
    if isinstance(progress, dict) and progress.get("vector") == "done":
        return "done"
    return None


def write_status(path: Path, snap: dict) -> None:
    path.write_text(json.dumps(snap, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gateway", default="http://localhost:8000")
    ap.add_argument("--limit", type=int, default=0, help="cap docs per KB (0 = all)")
    ap.add_argument("--concurrency", type=int, default=12, help="max in-flight uploads")
    ap.add_argument("--doc-timeout", type=float, default=900.0,
                    help="seconds before a stuck in-flight doc is abandoned")
    ap.add_argument("--status-file", type=Path,
                    default=Path("corpora/ingest_status.json"))
    args = ap.parse_args()
    root = Path.cwd()

    # Build the work list: (kb_id, pdf) pairs.
    work: list[tuple[str, Path, str]] = []
    kb_ids: dict[str, str] = {}
    for subdir, name, domain in KB_MAP:
        pdfs = sorted((root / subdir).rglob("*.pdf"))
        if args.limit:
            pdfs = pdfs[: args.limit]
        if not pdfs:
            continue
        kb_id = create_kb(args.gateway, name, domain)
        kb_ids[name] = kb_id
        print(f"KB {name} ({domain}) = {kb_id}: {len(pdfs)} PDFs")
        work += [(kb_id, p, domain) for p in pdfs]

    total = len(work)
    print(f"\ningesting {total} documents (concurrency={args.concurrency})\n")

    # Bounded in-flight window: keep <=concurrency docs uploaded-but-not-terminal.
    pending = list(work)          # not yet uploaded
    inflight: dict[str, Path] = {}  # doc_id -> pdf
    started_at: dict[str, float] = {}  # doc_id -> upload time (per-doc timeout)
    done: Counter[str] = Counter()  # terminal status -> count
    domains: Counter[str] = Counter()
    start = time.time()
    DOC_TIMEOUT = args.doc_timeout

    def snapshot() -> dict:
        elapsed = time.time() - start
        finished = sum(done.values())
        rate = finished / elapsed if elapsed > 0 else 0
        return {
            "total": total,
            "uploaded": total - len(pending),
            "in_flight": len(inflight),
            "done": done.get("done", 0),
            "failed": done.get("failed", 0),
            "timed_out": done.get("timed_out", 0),
            "skipped_too_large": done.get("skipped_too_large", 0),
            "pending_upload": len(pending),
            "detected_domains": dict(domains),
            "elapsed_s": round(elapsed, 1),
            "docs_per_min": round(rate * 60, 1),
            "kbs": kb_ids,
        }

    last_print = 0.0
    while pending or inflight:
        # Fill the window.
        while pending and len(inflight) < args.concurrency:
            kb_id, pdf, domain = pending.pop(0)
            doc_id = upload(args.gateway, kb_id, pdf, domain)
            if doc_id is False:
                done["skipped_too_large"] += 1
            elif doc_id:
                inflight[doc_id] = pdf
                started_at[doc_id] = time.time()
            else:
                done["failed"] += 1

        # Poll in-flight docs.
        for doc_id in list(inflight):
            doc = poll(args.gateway, doc_id)
            state = terminal_state(doc)
            if state is not None:
                done[state] += 1
                if state == "done" and doc.get("detected_domain"):
                    domains[str(doc["detected_domain"])] += 1
                inflight.pop(doc_id, None)
                started_at.pop(doc_id, None)
            elif time.time() - started_at.get(doc_id, 0) > DOC_TIMEOUT:
                # A doc stuck past the deadline (e.g. a slow OCR job) must not freeze the run.
                done["timed_out"] += 1
                inflight.pop(doc_id, None)
                started_at.pop(doc_id, None)

        snap = snapshot()
        write_status(args.status_file, snap)
        if time.time() - last_print >= 5:
            print(f"[{snap['elapsed_s']:>7.0f}s] done={snap['done']} failed={snap['failed']} "
                  f"timed_out={snap['timed_out']} in_flight={snap['in_flight']} "
                  f"pending={snap['pending_upload']} ({snap['docs_per_min']}/min)")
            last_print = time.time()
        time.sleep(2)

    snap = snapshot()
    write_status(args.status_file, snap)
    print(f"\nFINISHED: done={snap['done']} failed={snap['failed']} of {total} "
          f"in {snap['elapsed_s']}s")
    print(f"detected domains: {snap['detected_domains']}")
    return 0 if snap["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
