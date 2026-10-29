// The only place non-streaming calls go through. Never throws: any failure (network down, a non-JSON error page...)
// becomes { ok: false, message }. Model/user text is only ever rendered as React text or sanitized markdown.

export const JSON_HEADERS: Record<string, string> = { "Content-Type": "application/json" };

export interface ApiResult<T = any> {
  ok: boolean;
  status: number;
  data: T | null;
  message: string | null;
}

export const OFFLINE_MESSAGE = "Could not reach Morphie. Check your connection and try again.";

export async function callApi<T = any>(path: string, options?: RequestInit): Promise<ApiResult<T>> {
  let res: Response;
  try {
    res = await fetch(path, options);
  } catch {
    return { ok: false, status: 0, data: null, message: OFFLINE_MESSAGE };
  }
  let data: any = null;
  try {
    data = await res.json();
  } catch {
    /* not JSON */
  }
  const message = res.ok ? null : (data && (data.error || data.content)) || "Something went wrong. Please try again.";
  return { ok: res.ok, status: res.status, data, message };
}

// ---- Server-Sent Events over a POST body (EventSource can't POST) ----

export interface SseFrame {
  event: string;
  data: any;
}

export function parseFrame(frame: string): SseFrame {
  let event = "message";
  let data: any = null;
  for (const line of frame.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7);
    else if (line.startsWith("data: ")) {
      try {
        data = JSON.parse(line.slice(6));
      } catch {
        data = null;
      }
    }
  }
  return { event, data };
}

/** Reads a text/event-stream body and calls onFrame for each complete frame. */
export async function readSse(body: ReadableStream<Uint8Array>, onFrame: (f: SseFrame) => void): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      if (frame.trim()) onFrame(parseFrame(frame));
    }
  }
}

// ---- Uploads with progress (fetch can't report upload progress; XMLHttpRequest can) ----

export function uploadWithProgress<T = any>(
  path: string,
  form: FormData,
  headers: Record<string, string>,
  onProgress: (fraction: number) => void,
): Promise<ApiResult<T>> {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.min(1, e.loaded / e.total));
    };
    xhr.onerror = () => resolve({ ok: false, status: 0, data: null, message: OFFLINE_MESSAGE });
    xhr.onload = () => {
      let data: any = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* not JSON */
      }
      const ok = xhr.status >= 200 && xhr.status < 300;
      const message = ok ? null : (data && (data.error || data.content)) || "Something went wrong. Please try again.";
      resolve({ ok, status: xhr.status, data, message });
    };
    xhr.send(form);
  });
}
