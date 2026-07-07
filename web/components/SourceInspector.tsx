"use client";

import CitationPanel from "@/components/CitationPanel";
import type { Claim } from "@/lib/types";

/** Source inspector (R-UI-3): the provenance surface for an answer. Clicking a claim's
 *  citation highlights the exact page + bounding box it was grounded in, normalized by the
 *  source page's real dimensions. v1 is a schematic page render (not pdf.js); the citation
 *  click + bbox-highlight behavior is provided by CitationPanel, which this frames. */
export default function SourceInspector({ claims }: { claims: Claim[] }) {
  return (
    <div className="source-inspector">
      <h2>Source inspector</h2>
      <p className="muted" style={{ fontSize: "0.8rem" }}>
        Click a citation to see the page + span it was grounded in.
      </p>
      <CitationPanel claims={claims} />
    </div>
  );
}
