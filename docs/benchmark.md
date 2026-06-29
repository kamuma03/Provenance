# Vector-backend benchmark

Embedded vs dedicated-server vs in-database, behind one `VectorStorePort` (R23).
Deterministic embeddings ⇒ recall is an exact-NN sanity check; the comparison is
latency across architectures. Run: `python -m provenance_eval.benchmark_run`.

| Backend | Architecture | Docs | Ingest (ms) | p50 query (ms) | p95 (ms) | Recall@5 |
|---|---|---|---|---|---|---|
| faiss | embedded | 500 | 0.5 | 0.01 | 0.01 | 1.0 |
| qdrant | dedicated server | 500 | 16.3 | 0.12 | 0.12 | 1.0 |
| pgvector | in-database | 500 | 42.2 | 1.19 | 1.67 | 1.0 |
