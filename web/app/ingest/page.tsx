"use client";

import { useState } from "react";
import { createKb, getDocument, uploadDocument } from "@/lib/api";
import { DOMAINS, type ProcessingTier } from "@/lib/types";

async function fileToBase64(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

export default function IngestPage() {
  const [kbName, setKbName] = useState("My Knowledge Base");
  const [domain, setDomain] = useState<string>("generic");
  const [kbId, setKbId] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [tier, setTier] = useState<ProcessingTier>("full");
  const [status, setStatus] = useState<string>("");
  const [busy, setBusy] = useState(false);

  async function handleCreateKb() {
    const { id } = await createKb(kbName, domain);
    setKbId(id);
    if (typeof window !== "undefined") localStorage.setItem("kb", id);
  }

  async function handleUpload() {
    if (!file || !kbId) return;
    setBusy(true);
    setStatus("uploading…");
    try {
      const b64 = await fileToBase64(file);
      const { document_id } = await uploadDocument(kbId, file.name, b64, tier);
      for (let i = 0; i < 40; i++) {
        const doc = await getDocument(document_id);
        setStatus(`document ${document_id}: ${doc.status}`);
        if (doc.status === "done" || doc.status === "failed") break;
        await new Promise((r) => setTimeout(r, 1000));
      }
    } catch (e) {
      setStatus(`error: ${String(e)}`);
    } finally {
      setBusy(false);
    }
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
        {status && <p className="muted" style={{ marginTop: "0.75rem" }}>{status}</p>}
      </div>
    </div>
  );
}
