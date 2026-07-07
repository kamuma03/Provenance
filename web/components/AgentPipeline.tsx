"use client";

import type { StageView } from "@/lib/types";

const ICON: Record<string, string> = {
  pending: "○",
  active: "◍",
  done: "●",
  blocked: "⨯",
  failed: "⨯",
};

function label(name: string): string {
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** The live agent crew as an ordered pipeline (R-UI-2): Planner → Retriever → Critic →
 *  Synthesizer, each in a truthful state the backend actually reported. A refused answer
 *  surfaces the Critic in a `blocked` state — the pipeline never fakes a green Critic. */
export default function AgentPipeline({ stages }: { stages: StageView[] }) {
  return (
    <ol className="pipeline" aria-label="agent pipeline">
      {stages.map((s) => (
        <li key={s.name} className={`pipeline-stage state-${s.state}`} aria-current={s.state === "active"}>
          <span className="stage-icon" aria-hidden="true">{ICON[s.state] ?? "○"}</span>
          <span className="stage-name">{label(s.name)}</span>
          <span className="stage-state">{s.state}</span>
          {s.detail && <span className="stage-detail muted">{s.detail}</span>}
        </li>
      ))}
    </ol>
  );
}
