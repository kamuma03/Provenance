"use client";

/** Honest-refusal card (R-UI-4 / R31): shows the Critic's verdict and the specific claim(s)
 *  it could not ground, and offers suggested reformulations. It deliberately renders NO
 *  citation — a refusal must never fabricate a source. */
export default function RefusalCard({
  refusalReason,
  ungroundedClaims,
  suggestions,
}: {
  refusalReason?: string;
  ungroundedClaims?: string[];
  suggestions?: string[];
}) {
  return (
    <div className="refusal-card" role="alert">
      <div className="refusal-badge">Honest refusal</div>
      <p className="refusal-headline">
        Not supported by the corpus{refusalReason ? ` — ${refusalReason}` : ""}.
      </p>

      {ungroundedClaims && ungroundedClaims.length > 0 && (
        <div className="refusal-claims">
          <p className="muted">The Critic could not ground:</p>
          <ul>
            {ungroundedClaims.map((c, i) => (
              <li key={i} className="ungrounded-claim">{c}</li>
            ))}
          </ul>
        </div>
      )}

      {suggestions && suggestions.length > 0 && (
        <div className="refusal-suggestions">
          <p className="muted">Try instead:</p>
          <div className="chips">
            {suggestions.map((s, i) => (
              <span key={i} className="suggestion-chip">{s}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
