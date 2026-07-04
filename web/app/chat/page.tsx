"use client";

import { useEffect, useState } from "react";
import CitationPanel from "@/components/CitationPanel";
import EntityGraph from "@/components/EntityGraph";
import { streamQuery } from "@/lib/api";
import type { Answer, Evidence } from "@/lib/types";

interface Turn {
  query: string;
  text: string;
  answer: Answer | null;
  evidence: Evidence | null;
  phase: string;
}

export default function ChatPage() {
  const [kbId, setKbId] = useState("");
  const [input, setInput] = useState("");
  const [turn, setTurn] = useState<Turn | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") setKbId(localStorage.getItem("kb") ?? "");
  }, []);

  async function ask() {
    // Guard against re-entry: without this, pressing Enter while a stream is in flight would
    // interleave two answers' tokens into one garbled message (review M-15).
    if (busy || !input.trim() || !kbId) return;
    const query = input.trim();
    setInput("");
    setBusy(true);
    setTurn({ query, text: "", answer: null, evidence: null, phase: "retrieving" });
    const controller = new AbortController();
    try {
      await streamQuery(kbId, query, {
        signal: controller.signal,
        onStatus: (phase) => setTurn((t) => (t ? { ...t, phase } : t)),
        onToken: (text) => setTurn((t) => (t ? { ...t, text: t.text + text } : t)),
        onDone: (answer, evidence) =>
          setTurn((t) => (t ? { ...t, answer, evidence, phase: "done" } : t)),
        onError: (err) =>
          setTurn((t) => (t ? { ...t, text: `error: ${String(err)}`, phase: "error" } : t)),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1>Chat with your documents</h1>

      <div className="panel" style={{ marginBottom: "1rem" }}>
        <label>Knowledge base (R38 — scope)</label>
        <input value={kbId} onChange={(e) => setKbId(e.target.value)} placeholder="kb_…" />
      </div>

      <div className="panel" style={{ marginBottom: "1rem" }}>
        <div className="row">
          <input
            className="col"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !busy) ask();
            }}
            placeholder="Ask a question…"
          />
          <button onClick={ask} disabled={busy || !kbId}>Ask</button>
        </div>
      </div>

      {turn && (
        <div className="row">
          <div className="col panel">
            <div className="msg-user">{turn.query}</div>
            {turn.phase !== "done" && turn.phase !== "error" && (
              <p className="muted">· {turn.phase}…</p>
            )}
            <div className={`msg-assistant ${turn.answer?.refused ? "refusal" : ""}`}>
              {turn.text || (turn.phase === "done" ? "(no text)" : "")}
            </div>
            {turn.answer?.refused && (
              <p className="refusal" style={{ fontSize: "0.8rem" }}>
                Honest refusal — {turn.answer.refusal_reason ?? "not supported by the documents"}
              </p>
            )}
            {turn.answer && !turn.answer.refused && (
              <CitationPanel claims={turn.answer.claims} />
            )}
          </div>
          <div className="col panel">
            <h2>Entities used</h2>
            <EntityGraph entityIds={turn.evidence?.entity_ids ?? []} />
            {turn.evidence && (
              <p className="muted" style={{ fontSize: "0.8rem" }}>
                graph lift: {turn.evidence.graph_expanded ? "applied" : "none (vector floor)"} ·
                {" "}{turn.evidence.chunks.length} chunk(s) retrieved
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
