"use client";

import type { Subgraph } from "@/lib/types";

/** Per-answer entity graph (R-UI-8 / R37): named, typed nodes and the relations between them,
 *  taken from `evidence.subgraph`. SVG radial layout keeps the build dependency-free (a
 *  react-force-graph upgrade is a later enhancement). Edges are drawn as straight lines
 *  between the entities they relate. */
export default function EntityGraph({ subgraph }: { subgraph?: Subgraph }) {
  const nodes = subgraph?.nodes ?? [];
  const edges = subgraph?.edges ?? [];

  const w = 340;
  const h = 260;
  const cx = w / 2;
  const cy = h / 2;
  const r = 92;
  const n = nodes.length;

  if (n === 0) {
    return <p className="muted">No graph entities linked to this answer (vector-only evidence).</p>;
  }

  // Deterministic radial layout: position each node on the circle by its index.
  const pos = new Map<string, { x: number; y: number }>();
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2;
    pos.set(node.id, { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) });
  });

  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="entity graph">
      {/* Relations first so nodes render on top. */}
      {edges.map((e, i) => {
        const a = pos.get(e.src);
        const b = pos.get(e.dst);
        if (!a || !b) return null;
        return (
          <g key={`e${i}`}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#5b8cff" strokeWidth={1.5} />
            <title>{e.type}</title>
          </g>
        );
      })}
      {nodes.map((node) => {
        const p = pos.get(node.id)!;
        return (
          <g key={node.id}>
            <circle cx={p.x} cy={p.y} r={7} fill="#35c990" />
            <text x={p.x} y={p.y - 11} textAnchor="middle" fontSize="10" fill="#e6e8ee">
              {node.name}
            </text>
            <text x={p.x} y={p.y + 18} textAnchor="middle" fontSize="8" fill="#9aa3b2">
              {node.type}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
