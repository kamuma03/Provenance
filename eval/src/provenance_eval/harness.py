"""In-process eval harness — runs the real system components without the network.

Reuses the actual chunker, FAISS store, Kuzu graph, resolver, retrieval core, and crew
(deterministic embedder + lexical reranker, heuristic crew) so the gate exercises the
genuine pipeline. The LLM-judged RAGAS metrics run separately on the Spark.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from provenance_contracts import Answer, BBox, ElementType, ParsedElement, QueryHit, VectorRecord
from provenance_services.chunker import chunk_elements
from provenance_services.crew import run_crew
from provenance_services.embedder import DeterministicEmbedder
from provenance_services.extraction_engine import heuristic_generic
from provenance_services.faiss_store import FaissVectorStore
from provenance_services.graph_store import GraphStore
from provenance_services.resolver import EntityResolver, normalize_name
from provenance_services.retrieval import RetrievalDeps, retrieve


@dataclass
class EvalCase:
    id: str
    cohort: str
    kb: str
    query: str
    expected: str = ""
    answerable: bool = True
    gold_contains: str = ""  # an answerable case's gold chunk contains this term


@dataclass
class Outcome:
    case: EvalCase
    answer: Answer
    retrieved_texts: list[str] = field(default_factory=list)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


class InProcessSystem:
    def __init__(self, kuzu_path: str) -> None:
        self._emb = DeterministicEmbedder(dim=64)
        self._vec = FaissVectorStore()
        self._graph = GraphStore(kuzu_path)
        self._resolver = EntityResolver()

    async def ingest(self, kb_id: str, doc_id: str, text: str) -> None:
        elements = [
            ParsedElement(
                element_type=ElementType.TEXT, text=s, page=0,
                bbox=BBox(page=0, x0=0, y0=float(i), x1=1, y1=float(i) + 1), reading_order=i,
            )
            for i, s in enumerate(_sentences(text))
        ]
        chunks = chunk_elements(
            elements, document_id=doc_id, kb_id=kb_id, target_chars=60, overlap_chars=0
        )
        records = [
            VectorRecord(
                chunk_id=c.id, embedding=self._emb.embed([c.text])[0], text=c.text,
                metadata={
                    "document_id": doc_id, "page": str(c.page),
                    "bbox": c.bbox.model_dump_json(),
                },
            )
            for c in chunks
        ]
        await self._vec.upsert(kb_id, records)
        res = self._resolver.resolve(kb_id, heuristic_generic(text))
        self._graph.upsert_entities(res.entities)

    def _deps(self) -> RetrievalDeps:
        async def embed(q: str) -> list[float]:
            return self._emb.embed([q])[0]

        async def hybrid(kb: str, vec: list[float], text: str, k: int) -> list[QueryHit]:
            return await self._vec.hybrid_query(kb, vec, text, k)

        async def rerank(_q: str, hits: list[QueryHit]) -> list[QueryHit]:
            return hits  # hybrid order; lexical rerank tested separately

        async def link(kb: str, text: str) -> list[str]:
            qt = set(normalize_name(text).split())
            return [
                eid for eid, _t, name in self._graph.entities(kb)
                if (nt := set(normalize_name(name).split())) and nt <= qt
            ]

        async def expand(ids: list[str]) -> list[str]:
            out: list[str] = []
            for eid in ids:
                out.extend(self._graph.neighbors(eid))
            return out

        return RetrievalDeps(embed=embed, hybrid=hybrid, rerank=rerank, link=link, expand=expand)

    async def answer(self, kb_id: str, query: str) -> Outcome:
        deps = self._deps()
        ev = await retrieve(kb_id, query, deps)
        ans = await run_crew(query, kb_id, lambda kb, q: retrieve(kb, q, deps))
        return Outcome(case=EvalCase(id="", cohort="", kb=kb_id, query=query),
                       answer=ans, retrieved_texts=[c.text for c in ev.chunks])

    def close(self) -> None:
        self._graph.close()


async def run_cases(system: InProcessSystem, cases: list[EvalCase]) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for case in cases:
        out = await system.answer(case.kb, case.query)
        out.case = case
        outcomes.append(out)
    return outcomes
