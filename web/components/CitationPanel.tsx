"use client";

import { useState } from "react";
import type { Citation, Claim } from "@/lib/types";

/** Citation panel: click a citation to highlight its page + bbox (R36). */
export default function CitationPanel({ claims }: { claims: Claim[] }) {
  const [selected, setSelected] = useState<Citation | null>(null);

  return (
    <div>
      <h2>Citations</h2>
      {claims.length === 0 && <p className="muted">No grounded claims.</p>}
      {claims.map((claim, i) => (
        <div className="claim" key={i}>
          <div>{claim.text}</div>
          <div style={{ marginTop: 4 }}>
            {(claim.citations ?? []).map((c) => (
              <span
                key={c.chunk_id}
                className="cite"
                role="button"
                tabIndex={0}
                aria-pressed={selected?.chunk_id === c.chunk_id}
                onClick={() => setSelected(c)}
                onKeyDown={(e) => {
                  // Keyboard access: the core provenance feature must not be mouse-only (L-10).
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setSelected(c);
                  }
                }}
                style={{ marginRight: 10 }}
              >
                ↳ {c.chunk_id} · p{c.page}
              </span>
            ))}
          </div>
        </div>
      ))}

      {selected && (
        <div style={{ marginTop: "0.75rem" }}>
          <div className="muted" style={{ fontSize: "0.8rem" }}>
            page {selected.page} · bbox [{selected.bbox.x0.toFixed(0)}, {selected.bbox.y0.toFixed(0)},
            {selected.bbox.x1.toFixed(0)}, {selected.bbox.y1.toFixed(0)}]
          </div>
          <BBoxView c={selected} />
        </div>
      )}
    </div>
  );
}

/** Schematic page with the cited bbox highlighted (stands in for the PDF render). */
function BBoxView({ c }: { c: Citation }) {
  // Normalize using the source page's real dimensions when carried (L-10); fall back to
  // US-Letter only when the parse didn't record them.
  const pageW = c.bbox.page_width ?? 612;
  const pageH = c.bbox.page_height ?? 792;
  const left = `${(c.bbox.x0 / pageW) * 100}%`;
  const top = `${(c.bbox.y0 / pageH) * 100}%`;
  const width = `${(Math.max(c.bbox.x1 - c.bbox.x0, 8) / pageW) * 100}%`;
  const height = `${(Math.max(c.bbox.y1 - c.bbox.y0, 8) / pageH) * 100}%`;
  return (
    <div className="bbox-view">
      <div className="bbox-hl" style={{ left, top, width, height }} />
    </div>
  );
}
