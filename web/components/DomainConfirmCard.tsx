"use client";

import { useState } from "react";
import { DOMAINS } from "@/lib/types";

/** Detect-but-confirm card (R-UI-6 / R55): on a low-confidence domain detection the saga
 *  pauses and asks the user to Confirm the detected domain or Change it. `onConfirm` receives
 *  the override domain id, or `undefined` to keep the detected one. */
export default function DomainConfirmCard({
  detected,
  confidence,
  onConfirm,
}: {
  detected: string;
  confidence: number;
  onConfirm: (override?: string) => void;
}) {
  const [changing, setChanging] = useState(false);
  const [override, setOverride] = useState<string>("");

  return (
    <div className="domain-confirm">
      <p>
        Detected domain: <strong>{detected}</strong>{" "}
        {confidence > 0 && (
          <span className="muted">({Math.round(confidence * 100)}% confidence)</span>
        )}
      </p>

      {changing && (
        <div style={{ margin: "0.5rem 0" }}>
          <label htmlFor="domain-override">Change to</label>
          <select
            id="domain-override"
            value={override}
            onChange={(e) => setOverride(e.target.value)}
          >
            <option value="">Select a domain…</option>
            {DOMAINS.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>
      )}

      <div className="row" style={{ gap: "0.5rem" }}>
        <button type="button" onClick={() => onConfirm(override || undefined)}>
          Confirm
        </button>
        {!changing && (
          <button type="button" className="secondary" onClick={() => setChanging(true)}>
            Change
          </button>
        )}
      </div>
    </div>
  );
}
