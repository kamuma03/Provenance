import Link from "next/link";

export default function Home() {
  return (
    <div className="landing">
      <section className="hero">
        <h1 className="hero-title">Answers you can trace to the source.</h1>
        <p className="hero-sub">
          Provenance is a provenance-aware RAG + Knowledge Graph. Every claim is traced to its
          source span — the exact page and bounding box — and the system refuses honestly when
          the documents don&apos;t support an answer.
        </p>
        <div className="hero-cta">
          <Link href="/ingest" className="btn btn-primary">Ingest documents</Link>
          <Link href="/chat" className="btn btn-secondary">Chat with your corpus</Link>
        </div>
      </section>

      <section className="features">
        <div className="feature panel">
          <h3>Cited to the span</h3>
          <p className="muted">
            Click any claim to see the page and bounding box it was grounded in — not just a
            document name.
          </p>
        </div>
        <div className="feature panel">
          <h3>Multi-hop over a graph</h3>
          <p className="muted">
            Hybrid retrieval sets the floor; a knowledge graph adds entity context on top, so
            relational and comparative questions resolve.
          </p>
        </div>
        <div className="feature panel">
          <h3>Honest refusal</h3>
          <p className="muted">
            A strict Critic verifies every claim against the evidence. If it can&apos;t be
            grounded, the system refuses and names the ungrounded claim — it never guesses.
          </p>
        </div>
      </section>
    </div>
  );
}
