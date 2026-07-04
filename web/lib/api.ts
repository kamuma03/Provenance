import type { Answer, Evidence, StreamHandlers } from "./types";

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

export async function uploadDocument(
  kbId: string,
  source: string,
  contentB64: string,
  tier: string,
): Promise<{ document_id: string; status: string }> {
  return postJson(`/kb/${kbId}/documents`, { source, content_b64: contentB64, tier });
}

export async function getDocument(
  docId: string,
): Promise<{ id: string; kb_id: string; source: string; status: string }> {
  const res = await fetch(`${BASE}/documents/${docId}`);
  if (!res.ok) throw new Error(`document ${docId} → ${res.status}`);
  return res.json();
}

export async function kbStats(kbId: string): Promise<{ entity_count: number }> {
  const res = await fetch(`${BASE}/kb/${kbId}/stats`);
  if (!res.ok) throw new Error(`stats → ${res.status}`);
  return res.json();
}

/** Consume the SSE stream from POST /query/stream (R35). */
export async function streamQuery(
  kbId: string,
  query: string,
  handlers: StreamHandlers,
): Promise<void> {
  try {
    const res = await fetch(`${BASE}/query/stream`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ kb_id: kbId, query }),
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
  else if (event === "token") handlers.onToken?.(payload.text);
  else if (event === "done") handlers.onDone?.(payload.answer as Answer, payload.evidence as Evidence);
  else if (event === "error") handlers.onError?.(new Error(payload.message ?? "stream error"));
}
