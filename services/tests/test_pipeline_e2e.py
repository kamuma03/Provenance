"""Full ingestion pipeline, end to end with real engines — hermetic (no LLM, no network).

Exercises the whole spine in-process so every stage is genuinely run, not mocked:

    PDF  →  parse (pdfplumber, tables kept whole)
         →  chunk (page + bbox carried)
         →  vector DB (FAISS dense + BM25 hybrid retrieval)
         →  graph DB (Kuzu typed nodes/edges, queried back)
         →  ontology (domain schema enforced: off-schema types/predicates dropped)

Determinism: the offline DeterministicEmbedder gives stable vectors, and the entities/
relations are constructed to a known shape (the LLM extractor is covered separately by
test_ingestion_e2e.py against a live model). This test runs in the default suite.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("reportlab")

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet  # noqa: E402
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402


def _financial_pdf() -> bytes:
    """A born-digital 10-K-ish page: prose naming a company + officer, and a metrics table."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    s = getSampleStyleSheet()
    doc.build([
        Paragraph("Acme Robotics Inc Annual Report", s["Title"]),
        Paragraph(
            "Acme Robotics Inc is led by chief executive officer Jane Smith. The company "
            "reported strong results driven by its industrial automation segment, and cites "
            "supply-chain disruption as a principal risk factor for the coming fiscal year.",
            s["Normal"],
        ),
        Spacer(1, 12),
        Table(
            [["Financial Metric", "FY2023"], ["Total Revenue", "4.2 billion USD"],
             ["Net Income", "0.6 billion USD"]],
            style=TableStyle([
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ]),
        ),
    ])
    return buf.getvalue()


@pytest.mark.asyncio
async def test_pdf_to_vector_graph_and_ontology() -> None:
    from provenance_contracts import (
        REGISTRY,
        ElementType,
        EntityCandidate,
        RelationCandidate,
        VectorRecord,
    )
    from provenance_services.chunker import chunk_elements
    from provenance_services.embedder import DeterministicEmbedder
    from provenance_services.extraction_engine import validate_against_schema
    from provenance_services.faiss_store import FaissVectorStore
    from provenance_services.graph_store import GraphStore
    from provenance_services.parse_engine import parse_pdf_bytes
    from provenance_services.resolver import EntityResolver

    kb_id = "kb-acme"
    doc_id = "doc-10k-2023"

    # ── 1. PARSE ─────────────────────────────────────────────────────────────────────
    parsed = parse_pdf_bytes(_financial_pdf())
    assert parsed.pages == 1
    assert parsed.elements, "parse produced no elements"
    types = {e.element_type for e in parsed.elements}
    assert ElementType.TABLE in types, "the metrics table was not kept as a coherent unit (R68)"
    blob = " ".join(e.text for e in parsed.elements)
    assert "Acme Robotics" in blob and "Jane Smith" in blob
    for e in parsed.elements:  # every element carries real geometry for citation (R60)
        assert e.bbox.x1 >= e.bbox.x0 and e.bbox.y1 >= e.bbox.y0

    # ── 2. CHUNK ─────────────────────────────────────────────────────────────────────
    chunks = chunk_elements(parsed.elements, document_id=doc_id, kb_id=kb_id)
    assert chunks, "chunker produced no chunks"
    assert all(c.text.strip() for c in chunks)
    assert all(c.bbox.page == c.page for c in chunks)  # provenance preserved through chunking

    # ── 3. VECTOR DB (real FAISS index + BM25 hybrid) ────────────────────────────────
    embedder = DeterministicEmbedder()
    vectors = embedder.embed([c.text for c in chunks])
    store = FaissVectorStore()
    await store.upsert(
        kb_id,
        [
            VectorRecord(
                chunk_id=c.id, embedding=v, text=c.text,
                metadata={"document_id": doc_id, "page": str(c.page)},
            )
            for c, v in zip(chunks, vectors, strict=True)
        ],
    )
    query = "What revenue did the company report?"
    hits = await store.hybrid_query(kb_id, embedder.embed([query])[0], query, k=3)
    assert hits, "hybrid retrieval returned nothing"
    assert any("revenue" in h.text.lower() for h in hits), "the revenue chunk was not retrieved"
    assert all(h.metadata["document_id"] == doc_id for h in hits)  # provenance on every hit

    # ── 4. ONTOLOGY (domain schema enforced — repair-by-dropping, R16) ───────────────
    onto = REGISTRY["sec_financial"]
    raw_entities = [
        EntityCandidate(type="Company", canonical_name="Acme Robotics Inc"),
        EntityCandidate(type="Person", canonical_name="Jane Smith"),
        EntityCandidate(type="FinancialMetric", canonical_name="Total Revenue"),
        EntityCandidate(type="RiskFactor", canonical_name="Supply-chain disruption"),
        EntityCandidate(type="Spaceship", canonical_name="USS Enterprise"),  # OFF-schema
    ]
    raw_relations = [
        RelationCandidate(
            subject="Acme Robotics Inc", predicate="HAS_OFFICER", object="Jane Smith"
        ),
        RelationCandidate(
            subject="Acme Robotics Inc", predicate="REPORTED_METRIC", object="Total Revenue"
        ),
        RelationCandidate(  # OFF-schema predicate
            subject="Acme Robotics Inc", predicate="ABDUCTED_BY", object="USS Enterprise"
        ),
    ]
    entities, relations = validate_against_schema(raw_entities, raw_relations, onto)
    kept_types = {e.type for e in entities}
    assert "Spaceship" not in kept_types, "ontology did not drop the off-schema entity"
    assert all(e.type in onto.entity_types for e in entities)
    assert {r.predicate for r in relations} == {"HAS_OFFICER", "REPORTED_METRIC"}
    assert all(r.predicate in onto.relation_types for r in relations)  # ontology-clean edges

    # ── 5. GRAPH DB (Kuzu typed nodes/edges, then queried back) ──────────────────────
    resolved = EntityResolver().resolve(kb_id, entities)
    name_to_id = resolved.name_to_id
    graph_path = str(Path(tempfile.mkdtemp()) / "kuzu")
    graph = GraphStore(graph_path)
    try:
        written = graph.upsert_entities(resolved.entities)
        for r in relations:
            graph.write_relation(
                name_to_id[r.subject], r.predicate, name_to_id[r.object],
                kb_id=kb_id, document_id=doc_id,
            )

        # the typed graph is queryable and ontology-conformant
        assert graph.entity_count(kb_id) == written == len(entities)
        stored = {name: etype for _id, etype, name in graph.entities(kb_id)}
        assert stored["Acme Robotics Inc"] == "Company"
        assert stored["Jane Smith"] == "Person"

        # the HAS_OFFICER / REPORTED_METRIC edges resolve to real neighbors (multi-hop basis)
        acme_id = name_to_id["Acme Robotics Inc"]
        neighbors = set(graph.neighbors(acme_id))
        assert name_to_id["Jane Smith"] in neighbors
        assert name_to_id["Total Revenue"] in neighbors
        assert name_to_id["Supply-chain disruption"] not in neighbors  # no edge was asserted
    finally:
        graph.close()
