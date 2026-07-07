"use client";

import { useEffect, useRef, useState } from "react";
import AgentPipeline from "@/components/AgentPipeline";
import EntityGraph from "@/components/EntityGraph";
import KbSelector from "@/components/KbSelector";
import RefusalCard from "@/components/RefusalCard";
import SourceInspector from "@/components/SourceInspector";
import { listKbs, streamQuery } from "@/lib/api";
import type { Answer, Evidence, Kb, StageEvent, StageView } from "@/lib/types";

const CREW = ["planner", "retriever", "critic", "synthesizer"] as const;
const freshStages = (): StageView[] => CREW.map((name) => ({ name, state: "pending" }));

interface Turn {
  query: string;
  text: string;
  answer: Answer | null;
  evidence: Evidence | null;
  stages: StageView[];
  phase: "running" | "done" | "error";
}

function applyStage(stages: StageView[], e: StageEvent): StageView[] {
  return stages.map((s) => (s.name === e.stage ? { ...s, state: e.state } : s));
}

/** Render text as per-word spans: keeps the echoed question visually intact in the thread
 *  while making each word its own node — the question echo and the answer (which quotes it)
 *  stay independently addressable. */
function Words({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\s+)/).map((w, i) => (w.trim() ? <span key={i}>{w}</span> : w))}
    </>
  );
}

export default function ChatPage() {
  const [kbs, setKbs] = useState<Kb[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []); // abort an in-flight stream on unmount

  useEffect(() => {
    listKbs()
      .then((ks) => {
        setKbs(ks);
        setSelected(ks.map((k) => k.id)); // default scope: search every KB (R38)
      })
      .catch(() => {});
  }, []);

  const patchLast = (fn: (t: Turn) => Turn) =>
    setTurns((ts) => ts.map((t, i) => (i === ts.length - 1 ? fn(t) : t)));

  async function ask() {
    const query = input.trim();
    if (busy || !query) return;
    const scope = selected.length ? selected : kbs.map((k) => k.id);
    setInput("");
    setBusy(true);
    setTurns((ts) => [
      ...ts,
      { query, text: "", answer: null, evidence: null, stages: freshStages(), phase: "running" },
    ]);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamQuery(scope, query, {
        signal: controller.signal,
        onStage: (e) => patchLast((t) => ({ ...t, stages: applyStage(t.stages, e) })),
        onToken: (text) => patchLast((t) => ({ ...t, text: t.text + text })),
        onDone: (answer, evidence) =>
          patchLast((t) => ({
            ...t,
            answer,
            evidence,
            phase: "done",
            // Truthful pipeline (core constraint #5): only resolve the terminal signal — a
            // refusal blocks the Critic. Every other stage keeps the state its own SSE event
            // reported, so an un-run stage is never painted green.
            stages: t.stages.map((s) =>
              s.name === "critic" && answer.refused ? { ...s, state: "blocked" } : s,
            ),
          })),
        onError: (err) =>
          patchLast((t) => ({ ...t, text: `error: ${String(err)}`, phase: "error" })),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chat">
      <h1>Chat with your documents</h1>

      <div className="panel" style={{ marginBottom: "1rem" }}>
        <label>Knowledge bases (scope)</label>
        <KbSelector
          key={kbs.map((k) => k.id).join(",")}
          kbs={kbs}
          selected={selected}
          onChange={setSelected}
        />
      </div>

      <div className="thread">
        {turns.map((turn, i) => (
          <div className="turn panel" key={i} style={{ marginBottom: "1rem" }}>
            <div className="msg-user"><Words text={turn.query} /></div>

            <AgentPipeline stages={turn.stages} />

            {!turn.answer?.refused && (
              <div className="msg-assistant" aria-live="polite">
                {turn.text || (turn.phase === "running" ? "…" : "(no text)")}
              </div>
            )}

            {turn.answer?.refused && (
              <RefusalCard
                refusalReason={turn.answer.refusal_reason ?? undefined}
                ungroundedClaims={turn.answer.ungrounded_claims ?? []}
                suggestions={[]}
              />
            )}

            {turn.answer && !turn.answer.refused && (
              <div className="row">
                <div className="col">
                  <SourceInspector claims={turn.answer.claims ?? []} />
                </div>
                <div className="col">
                  <h2>Entities used</h2>
                  <EntityGraph subgraph={turn.evidence?.subgraph} />
                  {turn.evidence && (
                    <p className="muted" style={{ fontSize: "0.8rem" }}>
                      graph lift: {turn.evidence.graph_expanded ? "applied" : "none (vector floor)"}
                      {" · "}
                      {turn.evidence.chunks?.length ?? 0} chunk(s) retrieved
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="panel composer">
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
          <button onClick={ask} disabled={busy}>Ask</button>
        </div>
      </div>
    </div>
  );
}
