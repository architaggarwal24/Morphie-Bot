import { useCallback, useEffect, useRef, useState } from "react";
import { JSON_HEADERS, OFFLINE_MESSAGE, callApi, readSse } from "@/lib/api";
import { withLlmHeaders } from "@/lib/llm";
import { followupsEnabled, newTurnId } from "@/lib/prefs";

export type StepState = "active" | "done" | "error";

export interface Step {
  id: number;
  tool: string;
  state: StepState;
  input?: string;
  output?: string;
  ms?: number;
  links?: { title: string; url: string }[];
}

export interface Source {
  n?: number;
  document: string;
  document_id?: string;
  page?: number | null;
  snippet?: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "streaming" | "done" | "error" | "stopped";
  steps: Step[];
  thinking: boolean;
  sources: Source[];
  /** For assistant turns: the question that produced it (so it can be regenerated). */
  prompt?: string;
  /** Set when the turn failed: shown in an error card. */
  error?: string;
  /** The page's id for this question-and-answer pair. */
  turnId?: string;
  /** The server's id for this message in its history (only for saved turns). */
  serverId?: number;
  /** Suggested next questions (assistant turns). */
  followups?: string[];
  /** Restored from the server after a reload. */
  restored?: boolean;
}

export interface SendOptions {
  /** Force a tool for this question ("/calc", "/web"...). */
  tool?: string;
  /** Ask about just these documents (from @mentions); otherwise the panel's selection. */
  documentIds?: string[] | null;
}

let seq = 0;
const uid = () => `m${Date.now().toString(36)}${(seq++).toString(36)}`;

interface Options {
  /** null = ask about every document; a list = only these. Read at send time. */
  getDocumentIds: () => string[] | null;
  onResetFailed: (message: string) => void;
}

interface HistoryRow {
  id: number;
  role: "user" | "assistant";
  content: string;
  meta?: { sources?: Source[]; tools?: { tool: string; success: boolean }[] };
}

/** Server transcript -> messages, so a reload shows exactly what the model remembers. */
export function fromHistory(rows: HistoryRow[]): Message[] {
  const out: Message[] = [];
  let lastPrompt = "";
  for (const r of rows) {
    if (r.role === "user") {
      lastPrompt = r.content;
      out.push({ id: uid(), role: "user", content: r.content, status: "done", steps: [], thinking: false, sources: [], serverId: r.id, restored: true });
    } else {
      out.push({
        id: uid(),
        role: "assistant",
        content: r.content,
        status: "done",
        thinking: false,
        sources: r.meta?.sources ?? [],
        steps: (r.meta?.tools ?? []).map((t, i) => ({ id: i + 1, tool: t.tool, state: t.success ? "done" : "error" })),
        prompt: lastPrompt,
        serverId: r.id,
        restored: true,
      });
    }
  }
  return out;
}

/** One conversation, streamed over POST /chat/stream (SSE events: step / token / message / error). */
export function useChat({ getDocumentIds, onResetFailed }: Options) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const inFlight = useRef<{ controller: AbortController; turnId: string } | null>(null);
  const messagesRef = useRef<Message[]>([]);
  messagesRef.current = messages;

  // Tokens arrive faster than the screen refreshes: buffer them and paint once per frame.
  const pending = useRef<{ id: string; text: string } | null>(null);
  const frame = useRef(0);

  const patch = useCallback((id: string, fn: (m: Message) => Message) => {
    setMessages((list) => list.map((m) => (m.id === id ? fn(m) : m)));
  }, []);

  const flush = useCallback(() => {
    frame.current = 0;
    const p = pending.current;
    if (!p || !p.text) return;
    pending.current = { id: p.id, text: "" };
    patch(p.id, (m) => ({ ...m, content: m.content + p.text, thinking: false }));
  }, [patch]);

  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  /** After a reload: show the conversation the server still remembers. */
  const restore = useCallback(async () => {
    const result = await callApi<{ messages: HistoryRow[] }>("/chat/history");
    if (result.ok && result.data && !messagesRef.current.length) setMessages(fromHistory(result.data.messages || []));
    setRestoring(false);
  }, []);

  const loadFollowups = useCallback(
    async (botId: string) => {
      if (!followupsEnabled()) return;
      const result = await callApi<{ suggestions: string[] }>("/chat/followups", {
        method: "POST",
        headers: withLlmHeaders(JSON_HEADERS),
        body: "{}",
      });
      const list = result.ok ? result.data?.suggestions ?? [] : [];
      if (list.length) patch(botId, (m) => ({ ...m, followups: list }));
    },
    [patch],
  );

  const send = useCallback(
    async (raw: string, options: SendOptions = {}) => {
      const text = raw.trim();
      if (!text || inFlight.current) return;
      const turnId = newTurnId();
      const userMsg: Message = { id: uid(), role: "user", content: text, status: "done", steps: [], thinking: false, sources: [], turnId };
      const botId = uid();
      const botMsg: Message = { id: botId, role: "assistant", content: "", status: "streaming", steps: [], thinking: true, sources: [], prompt: text, turnId };
      // suggestions belong to the latest answer only
      setMessages((list) => [...list.map((m) => (m.followups ? { ...m, followups: undefined } : m)), userMsg, botMsg]);
      setBusy(true);
      const controller = new AbortController();
      inFlight.current = { controller, turnId };
      pending.current = { id: botId, text: "" };
      let stepSeq = 0;
      let finished = false;

      const fail = (message: string) => {
        flush();
        patch(botId, (m) => ({
          ...m,
          status: "error",
          thinking: false,
          error: message,
          steps: m.steps.map((s) => (s.state === "active" ? { ...s, state: "error" as const } : s)),
        }));
      };

      const documentIds = options.documentIds !== undefined ? options.documentIds : getDocumentIds();

      try {
        const res = await fetch("/chat/stream", {
          method: "POST",
          headers: withLlmHeaders(JSON_HEADERS),
          signal: controller.signal,
          body: JSON.stringify({ message: text, document_ids: documentIds, turn_id: turnId, ...(options.tool ? { tool: options.tool } : {}) }),
        });
        if (!res.ok || !res.body) {
          let data: any = null;
          try {
            data = await res.json();
          } catch {
            /* not JSON */
          }
          fail((data && (data.content || data.error)) || "Morphie couldn't process that. Please try again.");
        } else {
          await readSse(res.body, ({ event, data }) => {
            if (event === "step" && data) {
              flush();
              if (data.type === "thinking") patch(botId, (m) => ({ ...m, thinking: true }));
              else if (data.type === "discard_text") {
                pending.current = { id: botId, text: "" };
                patch(botId, (m) => ({ ...m, content: "" }));
              } else if (data.type === "tool_call")
                patch(botId, (m) => ({
                  ...m,
                  thinking: false,
                  steps: [...m.steps, { id: ++stepSeq, tool: String(data.tool), state: "active", input: data.input || undefined }],
                }));
              else if (data.type === "tool_result")
                patch(botId, (m) => {
                  const steps = [...m.steps];
                  for (let i = steps.length - 1; i >= 0; i--) {
                    if (steps[i].state === "active") {
                      steps[i] = {
                        ...steps[i],
                        state: data.success ? "done" : "error",
                        output: data.output || undefined,
                        ms: typeof data.ms === "number" ? data.ms : undefined,
                        links: Array.isArray(data.links) ? data.links : undefined,
                      };
                      break;
                    }
                  }
                  return { ...m, steps };
                });
            } else if (event === "token" && data) {
              pending.current = { id: botId, text: (pending.current?.text ?? "") + String(data.text ?? "") };
              if (!frame.current) frame.current = requestAnimationFrame(flush);
            } else if (event === "message" && data) {
              cancelAnimationFrame(frame.current);
              frame.current = 0;
              pending.current = null;
              finished = true;
              const turn = data.turn || {};
              setMessages((list) =>
                list.map((m) => {
                  if (m.id === userMsg.id && typeof turn.user_message_id === "number") return { ...m, serverId: turn.user_message_id };
                  if (m.id !== botId) return m;
                  return {
                    ...m,
                    status: "done",
                    thinking: false,
                    content: typeof data.content === "string" ? data.content : m.content,
                    sources: Array.isArray(data.sources) ? data.sources : [],
                    serverId: typeof turn.assistant_message_id === "number" ? turn.assistant_message_id : undefined,
                    steps: m.steps.map((s) => (s.state === "active" ? { ...s, state: "done" as const } : s)),
                  };
                }),
              );
            } else if (event === "error") {
              fail(String(data?.message ?? "Something went wrong."));
            }
          });
          // a stream that ends without a final message keeps whatever text arrived
          flush();
          patch(botId, (m) =>
            m.status === "streaming"
              ? { ...m, status: m.content ? "done" : "error", error: m.content ? undefined : "Morphie didn't answer. Please try again.", thinking: false }
              : m,
          );
        }
      } catch (err: any) {
        if (err && err.name === "AbortError") {
          flush();
          patch(botId, (m) => ({ ...m, status: "stopped", thinking: false, steps: m.steps.map((s) => (s.state === "active" ? { ...s, state: "error" as const } : s)) }));
        } else {
          fail(OFFLINE_MESSAGE);
        }
      } finally {
        cancelAnimationFrame(frame.current);
        frame.current = 0;
        pending.current = null;
        inFlight.current = null;
        setBusy(false);
      }
      if (finished) loadFollowups(botId);
    },
    [flush, getDocumentIds, patch, loadFollowups],
  );

  /** Stop: end the stream here and tell the server to drop the turn (it must not remember a half answer). */
  const stop = useCallback(() => {
    const current = inFlight.current;
    if (!current) return;
    current.controller.abort();
    callApi("/chat/cancel", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ turn_id: current.turnId }), keepalive: true });
  }, []);

  const reset = useCallback(async () => {
    if (inFlight.current) stop();
    const result = await callApi("/chat/reset", { method: "POST", headers: JSON_HEADERS, body: "{}" });
    if (!result.ok) {
      onResetFailed("Couldn't start a new chat. " + (result.message ?? ""));
      return false;
    }
    setMessages([]);
    return true;
  }, [onResetFailed, stop]);

  /**
   * Forget the question at `index` (and everything after it) on the server and here. Turns the server never saved
   * (errors, stopped) have no id and are only removed here. Returns false if the server refused.
   */
  const rewindTo = useCallback(async (index: number): Promise<boolean> => {
    const list = messagesRef.current;
    const saved = list.slice(index).find((m) => typeof m.serverId === "number");
    if (saved) {
      const result = await callApi("/chat/rewind", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ before_id: saved.serverId }) });
      if (!result.ok) return false;
    }
    setMessages(list.slice(0, index));
    return true;
  }, []);

  /** Regenerate: forget this answer (and its question) and ask the same question again. */
  const regenerate = useCallback(
    async (botId: string) => {
      if (inFlight.current) return;
      const list = messagesRef.current;
      const at = list.findIndex((m) => m.id === botId);
      if (at === -1 || !list[at].prompt) return;
      const userAt = at > 0 && list[at - 1].role === "user" ? at - 1 : at;
      const prompt = list[at].prompt!;
      if (await rewindTo(userAt)) send(prompt);
      else onResetFailed("Couldn't regenerate that answer. Please try again.");
    },
    [rewindTo, send, onResetFailed],
  );

  /** Edit & resend: forget this question and what followed; the caller puts its text back in the composer. */
  const editFrom = useCallback(
    async (userMsgId: string): Promise<string | null> => {
      if (inFlight.current) return null;
      const list = messagesRef.current;
      const at = list.findIndex((m) => m.id === userMsgId);
      if (at === -1) return null;
      const text = list[at].content;
      if (await rewindTo(at)) return text;
      onResetFailed("Couldn't edit that message. Please try again.");
      return null;
    },
    [rewindTo, onResetFailed],
  );

  return { messages, busy, restoring, restore, send, stop, reset, regenerate, editFrom };
}
