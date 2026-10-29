// Bring your own key: provider, model and API key live in THIS browser.
//
// The choice is saved in localStorage ("Remember on this device") or sessionStorage (until the tab closes) and is
// sent as X-LLM-* headers with each request - never in a body or URL. The server uses it for that request only and
// never stores or logs it. The key is only ever read into these headers; it is never rendered into the page.

import { local, read, remove, session, write } from "./storage";

export const LLM_KEY = "morphie-llm";

export interface LlmChoice {
  provider: string;
  model: string;
  key: string;
  /** Only for the "custom" provider (an OpenAI-compatible server the owner allowed). */
  baseUrl?: string;
}

export function loadLlm(): LlmChoice | null {
  for (const store of [local(), session()]) {
    const raw = read(store, LLM_KEY);
    if (!raw) continue;
    try {
      const cfg = JSON.parse(raw);
      if (cfg && typeof cfg.provider === "string") return cfg as LlmChoice;
    } catch {
      /* unreadable: treat as not set */
    }
  }
  return null;
}

export function isRemembered(): boolean {
  return !!read(local(), LLM_KEY);
}

export function clearLlm(): void {
  remove(local(), LLM_KEY);
  remove(session(), LLM_KEY);
}

export function saveLlm(cfg: LlmChoice, remember: boolean): void {
  clearLlm();
  const target = remember ? local() ?? session() : session();
  write(target, LLM_KEY, JSON.stringify(cfg));
}

/** Headers that carry the saved choice. Empty when nothing is saved (the server then uses its own provider). */
export function llmHeaders(): Record<string, string> {
  const cfg = loadLlm();
  const headers: Record<string, string> = {};
  if (!cfg || !cfg.provider) return headers;
  headers["X-LLM-Provider"] = cfg.provider;
  if (cfg.model) headers["X-LLM-Model"] = cfg.model;
  if (cfg.key) headers["X-LLM-Key"] = cfg.key;
  if (cfg.baseUrl) headers["X-LLM-Base-URL"] = cfg.baseUrl;
  return headers;
}

export function withLlmHeaders(base: Record<string, string> = {}): Record<string, string> {
  return { ...base, ...llmHeaders() };
}

export const MODEL_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,119}$/;
export const BASE_URL_PATTERN = /^https?:\/\/[A-Za-z0-9.-]+(:\d{1,5})?(\/[A-Za-z0-9._~/-]*)?$/;
export const KEY_PATTERN = /^[\x21-\x7e]{8,400}$/;
