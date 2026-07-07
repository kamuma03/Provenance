"use client";

import { useState } from "react";
import type { Kb } from "@/lib/types";

/** Multi-select knowledge-base picker (R-UI-1) — replaces pasting a raw `kb_…` id. Selecting
 *  several KBs scopes the query across all of them (R38 → `kb_ids[]`). Controlled by `selected`
 *  but tracks its own working set so a parent that doesn't echo the prop back still multi-selects. */
export default function KbSelector({
  kbs,
  selected,
  onChange,
}: {
  kbs: Kb[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const [picked, setPicked] = useState<string[]>(selected);

  function toggle(id: string) {
    const next = picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id];
    setPicked(next);
    onChange(next);
  }

  if (kbs.length === 0) {
    return <p className="muted">No knowledge bases yet — ingest a document first.</p>;
  }

  return (
    <div className="kb-selector" role="group" aria-label="knowledge bases">
      {kbs.map((kb) => {
        const on = picked.includes(kb.id);
        return (
          <button
            key={kb.id}
            type="button"
            role="checkbox"
            aria-checked={on}
            className={`kb-chip ${on ? "on" : ""}`}
            onClick={() => toggle(kb.id)}
          >
            <span className="kb-name">{kb.name}</span>
            <span className="kb-domain muted">{kb.domain_id}</span>
          </button>
        );
      })}
    </div>
  );
}
