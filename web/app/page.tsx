import Link from "next/link";

export default function Home() {
  return (
    <div>
      <h1>Provenance</h1>
      <p className="muted">
        Provenance-aware RAG + Knowledge Graph. Every answer traces to a source span — and
        the system refuses honestly when the documents don&apos;t support a claim.
      </p>
      <div className="row" style={{ marginTop: "1rem" }}>
        <Link href="/ingest" className="col panel" style={{ textDecoration: "none", color: "inherit" }}>
          <h2>① Ingest</h2>
          <p className="muted">
            Upload a document into a knowledge base. Auto domain-detection, a Quick/Full
            capability tier, and a graph + vector index built from it.
          </p>
        </Link>
        <Link href="/chat" className="col panel" style={{ textDecoration: "none", color: "inherit" }}>
          <h2>② Chat</h2>
          <p className="muted">
            Ask questions. Streaming, cited answers backed by hybrid retrieval + a knowledge
            graph — click a citation to see its page and bounding box.
          </p>
        </Link>
      </div>
    </div>
  );
}
