"use client";

import { useState } from "react";
import DomainConfirmCard from "@/components/DomainConfirmCard";
import SagaStepper from "@/components/SagaStepper";
import {
  confirmDocument,
  createKb,
  streamDocumentEvents,
  uploadDocument,
  type DocEvent,
} from "@/lib/api";
import { DOMAINS, type ProcessingTier, type StageState, type StageView } from "@/lib/types";

// The public saga vocabulary the stepper renders (mirrors ingestion.STAGES, R-BE-6).
const SAGA_STAGES = ["parse", "chunk", "detect", "extract", "graph", "embed", "vector"] as const;
const freshStages = (): StageView[] => SAGA_STAGES.map((name) => ({ name, state: "pending" }));

async function fileToBase64(file: File): Promise<string> {
  // Encode in 32KB chunks rather than one char at a time (O(n²), freezes the tab on big files).
  const bytes = new Uint8Array(await file.arrayBuffer());
  const CHUNK = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

export default function IngestPage() {
  const [kbName, setKbName] = useState("My Knowledge Base");
  const [domain, setDomain] = useState<string>("generic");
  const [kbId, setKbId] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [tier, setTier] = useState<ProcessingTier>("full");
  const [busy, setBusy] = useState(false);

  const [docId, setDocId] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [stages, setStages] = useState<StageView[]>(freshStages());
  const [confirm, setConfirm] = useState<{ detected: string; confidence: number } | null>(null);

  async function handleCreateKb() {
    const { id } = await createKb(kbName, domain);
    setKbId(id);
    if (typeof window !== "undefined") localStorage.setItem("kb", id);
  }

  function onEvent(evt: DocEvent) {
    // Per-stage progress advances a single step; lifecycle events set the coarse status and
    // (on the snapshot) seed the whole stepper from the persisted progress map.
    if (evt.stage && evt.state) {
      setStages((prev) =>
        prev.map((s) => (s.name === evt.stage ? { ...s, state: evt.state as StageState } : s)),
      );
      return;
    }
    if (evt.status) {
      setStatus(evt.status);
      if (evt.progress) {
        setStages(
          SAGA_STAGES.map((name) => ({
            name,
            state: (evt.progress?.[name] as StageState) ?? "pending",
          })),
        );
      }
      if (evt.status === "awaiting_confirm") {
        setConfirm({
          detected: evt.detected_domain ?? "generic",
          confidence: evt.detection_confidence ?? 0,
        });
      } else if (evt.status === "done") {
        setStages((prev) => prev.map((s) => ({ ...s, state: "done" })));
      } else if (evt.status === "failed") {
        setStages((prev) => {
          const i = prev.findIndex((s) => s.state === "active");
          return prev.map((s, j) => (j === i ? { ...s, state: "failed" } : s));
        });
      }
    }
  }

  async function handleUpload() {
    if (!file || !kbId) return;
    setBusy(true);
    setStatus("uploading…");
    setStages(freshStages());
    setConfirm(null);
    try {
      const b64 = await fileToBase64(file);
      const { document_id } = await uploadDocument(kbId, file.name, b64, tier);
      setDocId(document_id);
      // Live feed replaces the old 40× poll loop (R-BE-7 / R-UI-5).
      await streamDocumentEvents(document_id, {
        onStatus: onEvent,
        onError: () => setStatus("connection to the ingest feed was lost"),
      });
    } catch (e) {
      setStatus(`error: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm(override?: string) {
    if (!docId) return;
    setConfirm(null);
    setStatus("confirming…");
    await confirmDocument(docId, override);
    // The saga resumes; a fresh feed carries the remaining stages to completion.
    await streamDocumentEvents(docId, {
      onStatus: onEvent,
      onError: () => setStatus("connection to the ingest feed was lost"),
    });
  }

  return (
    <div>
      <h1>Ingest a document</h1>

      <div className="panel" style={{ marginBottom: "1rem" }}>
        <h2>1 · Knowledge base</h2>
        <div className="row">
          <div className="col">
            <label>Name</label>
            <input value={kbName} onChange={(e) => setKbName(e.target.value)} />
          </div>
          <div className="col">
            <label>Domain (the fixed schema; &quot;generic&quot; lets detection fall back)</label>
            <select value={domain} onChange={(e) => setDomain(e.target.value)}>
              {DOMAINS.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </div>
        </div>
        <div style={{ marginTop: "0.75rem" }}>
          <button onClick={handleCreateKb}>Create knowledge base</button>
          {kbId && <span className="pill" style={{ marginLeft: "0.75rem" }}>kb: {kbId}</span>}
        </div>
      </div>

      <div className="panel">
        <h2>2 · Upload</h2>
        <label>Document (PDF / text)</label>
        <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />

        <label style={{ marginTop: "0.75rem" }}>Capability tier</label>
        <div className="row">
          <label className="pill" style={{ cursor: "pointer" }}>
            <input type="radio" style={{ width: "auto", marginRight: 6 }}
              checked={tier === "quick"} onChange={() => setTier("quick")} />
            Quick — vector only
          </label>
          <label className="pill" style={{ cursor: "pointer" }}>
            <input type="radio" style={{ width: "auto", marginRight: 6 }}
              checked={tier === "full"} onChange={() => setTier("full")} />
            Full — vector + graph + schema
          </label>
        </div>

        <div style={{ marginTop: "0.75rem" }}>
          <button onClick={handleUpload} disabled={!file || !kbId || busy}>
            {busy ? "Processing…" : "Upload & build"}
          </button>
        </div>
      </div>

      {docId && (
        <div className="panel" style={{ marginTop: "1rem" }}>
          <h2>3 · Ingestion</h2>
          <p className="muted" style={{ fontSize: "0.8rem" }}>
            {docId} · {status}
          </p>
          <SagaStepper stages={stages} />
          {confirm && (
            <div style={{ marginTop: "1rem" }}>
              <DomainConfirmCard
                detected={confirm.detected}
                confidence={confirm.confidence}
                onConfirm={handleConfirm}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
