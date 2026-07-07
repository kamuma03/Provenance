import type { Answer, Evidence, Kb, StreamHandlers } from "./types";

const BASE = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8000";

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return (await res.json()) as T;
}

export async function createKb(name: string, domainId: string): Promise<{ id: string }> {
  return postJson("/kb", { name, domain_id: domainId });
}

/** List knowledge bases for the selector (R-BE-1 / R-UI-1). */
export async function listKbs(): Promise<Kb[]> {
  const res = await fetch(`${BASE}/kb`);
  if (!res.ok) throw new Error(`kb → ${res.status}`);
  return res.json();
}

export async function uploadDocument(
  kbId: string,
  source: string,
  contentB64: string,
  tier: string,
): Promise<{ document_id: string; status: string }> {
  return postJson(`/kb/${kbId}/documents`, { source, content_b64: contentB64, tier });
}

// Document view widened with provenance + per-stage progress (R-BE-10) for the stepper/panel.
export interface DocumentView {
  id: string;
  kb_id: string;
  source: string;
  status: string;
  detected_domain?: string | null;
  detection_confidence?: number | null;
  schema_version?: string | null;
  parse_method?: string | null;
  ocr_engine?: string | null;
  trace_id?: string | null;
  progress?: Record<string, string> | null;
}

export async function getDocument(docId: string): Promise<DocumentView> {
  const res = await fetch(`${BASE}/documents/${docId}`);
  if (!res.ok) throw new Error(`document ${docId} → ${res.status}`);
  return res.json();
}

export async function confirmDocument(docId: string, domainId?: string): Promise<void> {
  await postJson(`/documents/${docId}/confirm`, domainId ? { domain_id: domainId } : {});
}

/** Consume the live ingest feed SSE (R-BE-7): each `status` event is a saga status / per-stage
 *  progress payload. Resolves when the stream closes (terminal state or disconnect). */
export interface DocEvent {
  document_id?: string;
  status?: string;
  stage?: string;
  state?: string;
  detected_domain?: string | null;
  detection_confidence?: number | null;
  progress?: Record<string, string> | null;
  message?: string;
}
export async function streamDocumentEvents(
  docId: string,
  handlers: { onStatus?: (evt: DocEvent) => void; onError?: (err: unknown) => void; signal?: AbortSignal },
): Promise<void> {
  try {
    const res = await fetch(`${BASE}/documents/${docId}/events`, { signal: handlers.signal });
    if (!res.ok) throw new Error(`events → ${res.status}`);
    if (!res.body) throw new Error("no response body");
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) >= 0) {
        const raw = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        let event = "message";
        let data = "";
        for (const line of raw.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (event === "status" && data) handlers.onStatus?.(JSON.parse(data) as DocEvent);
      }
    }
  } catch (err) {
    handlers.onError?.(err);
  }
}

export async function kbStats(kbId: string): Promise<{ entity_count: number }> {
  const res = await fetch(`${BASE}/kb/${kbId}/stats`);
  if (!res.ok) throw new Error(`stats → ${res.status}`);
  return res.json();
}

/** Consume the SSE stream from POST /query/stream (R35, R-BE-4): live crew stage events,
 *  then the verified answer text token-by-token after the Critic approves. Multi-KB scope
 *  (R38): pass the selected `kbIds`. */
export async function streamQuery(
  kbIds: string[],
  query: string,
  handlers: StreamHandlers,
): Promise<void> {
  try {
    const res = await fetch(`${BASE}/query/stream`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ kb_ids: kbIds, query }),
      signal: handlers.signal,
    });
    if (!res.ok) throw new Error(`query/stream → ${res.status}`);
    if (!res.body) throw new Error("no response body");
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) >= 0) {
        const raw = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        dispatchEvent(raw, handlers);
      }
    }
  } catch (err) {
    handlers.onError?.(err);
  }
}

function dispatchEvent(raw: string, handlers: StreamHandlers): void {
  let event = "message";
  let data = "";
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return;
  const payload = JSON.parse(data);
  if (event === "status") handlers.onStatus?.(payload.phase);
  else if (event === "stage") handlers.onStage?.(payload);
  else if (event === "token") handlers.onToken?.(payload.text);
  else if (event === "done") handlers.onDone?.(payload.answer as Answer, payload.evidence as Evidence);
  else if (event === "error") handlers.onError?.(new Error(payload.message ?? "stream error"));
}
