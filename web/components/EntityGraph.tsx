"use client";

/** Force-graph of the entities used in the answer (R37). SVG radial layout — a
 *  react-force-graph upgrade is a later enhancement; this keeps the build dependency-free. */
export default function EntityGraph({ entityIds }: { entityIds: string[] }) {
  const w = 320;
  const h = 240;
  const cx = w / 2;
  const cy = h / 2;
  const r = 85;
  const n = entityIds.length;

  if (n === 0) {
    return <p className="muted">No graph entities linked to this answer (vector-only evidence).</p>;
  }

  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="entity graph">
      {entityIds.map((id, i) => {
        const angle = (2 * Math.PI * i) / n;
        const x = cx + r * Math.cos(angle);
        const y = cy + r * Math.sin(angle);
        return (
          <g key={id}>
            <line x1={cx} y1={cy} x2={x} y2={y} stroke="#2a2f3a" strokeWidth={1} />
            <circle cx={x} cy={y} r={9} fill="#5b8cff" />
            <title>{id}</title>
          </g>
        );
      })}
      <circle cx={cx} cy={cy} r={13} fill="#e6e8ee" />
      <text x={cx} y={cy + 26} textAnchor="middle" fontSize="10" fill="#9aa3b2">
        answer
      </text>
    </svg>
  );
}
