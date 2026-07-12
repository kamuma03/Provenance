"""Fetch a corpus for the Built domains (R17): SEC 10-Ks + arXiv papers.

Downloads land in ``corpora/`` (gitignored). SEC EDGAR primary documents are HTML;
they are printed to born-digital PDF via headless Chromium so the parse service's
digital-first path (R61, pdfplumber text layer) applies. arXiv PDFs are fetched
as-is. Both sources are polite: EDGAR gets a declared User-Agent and stays well
below its 10 req/s ceiling; arXiv is throttled to one request every 3 seconds.

The most-recent 10-K per company keeps the stable name ``{ticker}-10k.pdf`` (the
golden set cites these); older filings are suffixed with their filing date. The
run is idempotent — existing files are skipped — so it resumes after interruption.

Usage:
    python scripts/fetch_corpus.py [--sec] [--arxiv] [--out corpora]
                                   [--sec-target N] [--arxiv-target N]
    (no flags = fetch both; defaults target ~1000 documents total)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

EDGAR_UA = "Provenance research corpus builder mukashifna@gmail.com"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# A broad spread of large/mid-cap filers whose 10-Ks are text-rich and table-bearing.
SEC_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM", "V", "JNJ",
    "WMT", "PG", "XOM", "KO", "PEP", "CSCO", "ORCL", "INTC", "IBM", "NFLX",
    "AMD", "BA", "MA", "HD", "CVX", "ABBV", "PFE", "MRK", "TMO", "ABT",
    "COST", "MCD", "DIS", "ADBE", "CRM", "ACN", "NKE", "TXN", "QCOM", "AMGN",
    "HON", "UNH", "LLY", "AVGO", "DHR", "LIN", "PM", "UPS", "LOW", "SBUX",
    "CAT", "GS", "MS", "BLK", "AXP", "SPGI", "GE", "MMM", "BKNG", "GILD",
    "ISRG", "NOW", "INTU", "AMAT", "MU", "LRCX", "ADI", "REGN", "VRTX", "PYPL",
    "T", "VZ", "CMCSA", "PEP", "MDT", "BMY", "CVS", "CI", "SO", "DUK",
    "BDX", "SYK", "ZTS", "MMC", "CB", "PGR", "USB", "PNC", "SCHW", "C",
    "WFC", "BAC", "F", "GM", "DE", "LMT", "RTX", "NOC", "GD", "EMR",
    "FDX", "TGT", "DG", "EL", "CL", "KMB", "GIS", "MO", "KHC", "MDLZ",
    "ADP", "FIS", "ICE", "CME", "AON", "TRV", "MET", "AIG", "PRU", "ALL",
]

# arXiv topic buckets: AI, medical, engineering.
ARXIV_BUCKETS = [
    ("ai", "cat:cs.LG OR cat:cs.CL OR cat:cs.AI OR cat:stat.ML"),
    ("medical", "cat:eess.IV OR cat:q-bio.QM OR cat:q-bio.NC OR cat:physics.med-ph"),
    ("engineering", "cat:eess.SY OR cat:cs.RO OR cat:eess.SP OR cat:physics.app-ph"),
]
ARXIV_API = "http://export.arxiv.org/api/query"
ARXIV_PAGE = 200  # ids fetched per API page


def _get(url: str, ua: str, retries: int = 4) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - retry any transient fetch error
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt + 1} after error: {exc}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def _chromium() -> str:
    for candidate in ("chromium-browser", "chromium", "google-chrome"):
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError("no chromium/chrome found for HTML->PDF conversion")


def html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    subprocess.run(
        [
            _chromium(),
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path.resolve()}",
            html_path.resolve().as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=420,
    )


def _tenk_filings(cik: int) -> list[tuple[str, str, str]]:
    """Return (accession, primary_document, filing_date) for a company's 10-Ks,
    most-recent first, from the EDGAR submissions 'recent' block."""
    subs = json.loads(_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", EDGAR_UA))
    recent = subs["filings"]["recent"]
    out: list[tuple[str, str, str]] = []
    for i, form in enumerate(recent["form"]):
        if form == "10-K" and recent["primaryDocument"][i].lower().endswith((".htm", ".html")):
            out.append(
                (
                    recent["accessionNumber"][i].replace("-", ""),
                    recent["primaryDocument"][i],
                    recent["filingDate"][i],
                )
            )
    return out


def fetch_sec(out_dir: Path, target: int, per_company: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tickers = json.loads(_get(SEC_TICKERS_URL, EDGAR_UA))
    cik_by_ticker = {row["ticker"]: int(row["cik_str"]) for row in tickers.values()}

    saved: list[Path] = []
    seen_tickers: set[str] = set()
    for ticker in SEC_TICKERS:
        if len(saved) >= target:
            break
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)
        cik = cik_by_ticker.get(ticker)
        if cik is None:
            print(f"[sec] {ticker}: no CIK, skipping", file=sys.stderr)
            continue
        try:
            filings = _tenk_filings(cik)
        except Exception as exc:  # noqa: BLE001
            print(f"[sec] {ticker}: submissions fetch failed: {exc}", file=sys.stderr)
            continue
        if not filings:
            print(f"[sec] {ticker}: no 10-K, skipping", file=sys.stderr)
            continue

        for n, (accession, primary, filing_date) in enumerate(filings[:per_company]):
            if len(saved) >= target:
                break
            # Most-recent keeps the stable name the golden set cites; older ones dated.
            name = f"{ticker.lower()}-10k.pdf" if n == 0 else f"{ticker.lower()}-10k-{filing_date}.pdf"
            pdf_path = out_dir / name
            if pdf_path.exists():
                print(f"[sec] {ticker} {filing_date}: present")
                saved.append(pdf_path)
                continue
            doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{primary}"
            print(f"[sec] {ticker}: 10-K filed {filing_date} <- {primary}")
            try:
                html = _get(doc_url, EDGAR_UA)
                html_path = out_dir / f".{ticker.lower()}-{filing_date}.htm"
                html_path.write_bytes(html)
                try:
                    html_to_pdf(html_path, pdf_path)
                finally:
                    html_path.unlink(missing_ok=True)
                if pdf_path.exists():
                    saved.append(pdf_path)
            except Exception as exc:  # noqa: BLE001 - one bad filing must not kill the run
                print(f"[sec] {ticker} {filing_date}: failed ({exc})", file=sys.stderr)
                pdf_path.unlink(missing_ok=True)
            time.sleep(0.4)  # stay far below EDGAR's 10 req/s ceiling
    print(f"[sec] {len(saved)} filings")
    return saved


def _arxiv_ids(query: str, want: int) -> list[str]:
    ids: list[str] = []
    start = 0
    while len(ids) < want:
        url = (
            f"{ARXIV_API}?search_query={urllib.request.quote(query)}"
            f"&start={start}&max_results={ARXIV_PAGE}"
            f"&sortBy=submittedDate&sortOrder=descending"
        )
        feed = _get(url, EDGAR_UA).decode("utf-8", errors="replace")
        page = re.findall(r"<id>http://arxiv\.org/abs/([^<]+)</id>", feed)
        if not page:
            break
        ids.extend(p.strip() for p in page)
        start += ARXIV_PAGE
        time.sleep(3)  # politeness between API pages
    return ids[:want]


def fetch_arxiv(out_dir: Path, per_bucket: int) -> list[Path]:
    saved: list[Path] = []
    for bucket, query in ARXIV_BUCKETS:
        bucket_dir = out_dir / bucket
        bucket_dir.mkdir(parents=True, exist_ok=True)
        # Over-fetch ids a little to absorb non-PDF / withdrawn entries.
        ids = _arxiv_ids(query, int(per_bucket * 1.15) + 5)
        got = 0
        for clean in ids:
            if got >= per_bucket:
                break
            slug = clean.replace("/", "-")
            pdf_path = bucket_dir / f"arxiv-{slug}.pdf"
            if pdf_path.exists():
                saved.append(pdf_path)
                got += 1
                continue
            try:
                pdf = _get(f"https://arxiv.org/pdf/{clean}", EDGAR_UA)
            except Exception as exc:  # noqa: BLE001
                print(f"[arxiv:{bucket}] {clean}: failed ({exc})", file=sys.stderr)
                time.sleep(3)
                continue
            if not pdf.startswith(b"%PDF"):
                print(f"[arxiv:{bucket}] {clean}: not a PDF, skipping", file=sys.stderr)
                time.sleep(3)
                continue
            pdf_path.write_bytes(pdf)
            saved.append(pdf_path)
            got += 1
            if got % 25 == 0:
                print(f"[arxiv:{bucket}] {got}/{per_bucket}")
            time.sleep(3)  # arXiv politeness interval
        print(f"[arxiv:{bucket}] {got} papers")
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sec", action="store_true")
    parser.add_argument("--arxiv", action="store_true")
    parser.add_argument("--out", default="corpora", type=Path)
    parser.add_argument("--sec-target", type=int, default=100)
    parser.add_argument("--arxiv-target", type=int, default=900)
    parser.add_argument("--sec-per-company", type=int, default=4)
    args = parser.parse_args()
    do_all = not (args.sec or args.arxiv)

    total: list[Path] = []
    if args.sec or do_all:
        total += fetch_sec(args.out / "sec_financial", args.sec_target, args.sec_per_company)
    if args.arxiv or do_all:
        per_bucket = -(-args.arxiv_target // len(ARXIV_BUCKETS))  # ceil-divide across buckets
        total += fetch_arxiv(args.out / "research_papers", per_bucket)
    print(f"\n{len(total)} documents in {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
