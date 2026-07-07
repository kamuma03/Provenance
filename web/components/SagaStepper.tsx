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

/** Ingestion saga as a 7-stage stepper (R-UI-5): parse → chunk → detect → extract → graph →
 *  embed → vector. Fed by the live SSE feed (R-BE-7); each stage shows the state (and any
 *  detail, e.g. a percentage) the saga actually reported — no decorative progress. */
export default function SagaStepper({ stages }: { stages: StageView[] }) {
  return (
    <ol className="stepper" aria-label="ingestion saga">
      {stages.map((s) => (
        <li key={s.name} className={`step state-${s.state}`} aria-current={s.state === "active"}>
          <span className="step-icon" aria-hidden="true">{ICON[s.state] ?? "○"}</span>
          <span className="step-name">{label(s.name)}</span>
          {s.detail && <span className="step-detail muted">{s.detail}</span>}
        </li>
      ))}
    </ol>
  );
}
