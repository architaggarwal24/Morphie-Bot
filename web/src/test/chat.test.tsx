import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useChat } from "@/hooks/useChat";
import { saveLlm } from "@/lib/llm";
import { setFollowupsEnabled } from "@/lib/prefs";

function sseResponse(frames: string[]) {
  const enc = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(c) {
        frames.forEach((f) => c.enqueue(enc.encode(f)));
        c.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}
const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

describe("chat streaming", () => {
  it("sends the saved key as headers, never in the body or URL", async () => {
    saveLlm({ provider: "openai", model: "", key: "sk-secret-abcdef" }, true);
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(sseResponse([frame("message", { content: "ok", sources: [] })]));
    const { result } = renderHook(() => useChat({ getDocumentIds: () => ["d1"], onResetFailed: vi.fn() }));
    await act(() => result.current.send("hello"));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/chat/stream");
    expect((init.headers as Record<string, string>)["X-LLM-Key"]).toBe("sk-secret-abcdef");
    expect(JSON.parse(String(init.body))).toEqual({ message: "hello", document_ids: ["d1"], turn_id: expect.stringMatching(/^[A-Za-z0-9_-]{8,64}$/) });
    expect(String(init.body)).not.toContain("sk-secret");
  });

  it("turns steps, tokens and the final message into one assistant turn", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        frame("step", { type: "thinking" }),
        frame("step", { type: "tool_call", tool: "calculator" }),
        frame("step", { type: "tool_result", tool: "calculator", success: true }),
        frame("token", { text: "100 " }),
        frame("message", { content: "100 it is.", sources: [{ document: "a.pdf", page: 2 }] }),
      ]),
    );
    const { result } = renderHook(() => useChat({ getDocumentIds: () => null, onResetFailed: vi.fn() }));
    await act(() => result.current.send("20% of 500"));
    const bot = result.current.messages[1];
    expect(result.current.messages[0]).toMatchObject({ role: "user", content: "20% of 500" });
    expect(bot).toMatchObject({ role: "assistant", status: "done", content: "100 it is.", thinking: false, prompt: "20% of 500" });
    expect(bot.steps).toEqual([{ id: 1, tool: "calculator", state: "done" }]);
    expect(bot.sources).toEqual([{ document: "a.pdf", page: 2 }]);
    expect(result.current.busy).toBe(false);
  });

  it("shows the server's error event, and HTTP errors, as an error card", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(sseResponse([frame("error", { message: "Model said no", code: "x" })]));
    const { result } = renderHook(() => useChat({ getDocumentIds: () => null, onResetFailed: vi.fn() }));
    await act(() => result.current.send("hi"));
    expect(result.current.messages[1]).toMatchObject({ status: "error", error: "Model said no" });

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({ error: "Too long" }), { status: 413 }));
    await act(() => result.current.send("again"));
    expect(result.current.messages[3]).toMatchObject({ status: "error", error: "Too long" });
  });

  it("reports a network failure in plain words", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const { result } = renderHook(() => useChat({ getDocumentIds: () => null, onResetFailed: vi.fn() }));
    await act(() => result.current.send("hi"));
    expect(result.current.messages[1].error).toMatch(/Could not reach Morphie/);
  });

  it("stop() aborts the request and marks the turn stopped", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_url, init) =>
        new Promise((_, reject) => {
          (init as RequestInit).signal!.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
        }),
    );
    const { result } = renderHook(() => useChat({ getDocumentIds: () => null, onResetFailed: vi.fn() }));
    let pending: Promise<void>;
    act(() => {
      pending = result.current.send("long one");
    });
    await waitFor(() => expect(result.current.busy).toBe(true));
    await act(async () => {
      result.current.stop();
      await pending;
    });
    expect(result.current.messages[1].status).toBe("stopped");
  });

  it("new chat clears the conversation only if the server agreed", async () => {
    setFollowupsEnabled(false);
    const onResetFailed = vi.fn();
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(sseResponse([frame("message", { content: "hey", sources: [] })]))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: "nope" }), { status: 500 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    const { result } = renderHook(() => useChat({ getDocumentIds: () => null, onResetFailed }));
    await act(() => result.current.send("hi"));
    await act(async () => {
      await result.current.reset();
    });
    expect(onResetFailed).toHaveBeenCalled();
    expect(result.current.messages).toHaveLength(2);
    await act(async () => {
      await result.current.reset();
    });
    expect(result.current.messages).toHaveLength(0);
  });

  it("Stop tells the server to drop the turn", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((url, init) => {
      if (String(url) === "/chat/cancel") return Promise.resolve(new Response("{}", { status: 200 }));
      return new Promise((_, reject) => {
        (init as RequestInit).signal!.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
      });
    });
    const { result } = renderHook(() => useChat({ getDocumentIds: () => null, onResetFailed: vi.fn() }));
    let pending: Promise<void>;
    act(() => {
      pending = result.current.send("long one");
    });
    await waitFor(() => expect(result.current.busy).toBe(true));
    const turnId = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body)).turn_id;
    await act(async () => {
      result.current.stop();
      await pending;
    });
    const cancel = fetchMock.mock.calls.find((c) => String(c[0]) === "/chat/cancel")!;
    expect(JSON.parse(String((cancel[1] as RequestInit).body))).toEqual({ turn_id: turnId });
    expect(result.current.messages[1].status).toBe("stopped");
  });

  it("text written before a tool call is withdrawn, then the tool details arrive", async () => {
    setFollowupsEnabled(false);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        frame("token", { text: "Let me check" }),
        frame("step", { type: "discard_text" }),
        frame("step", { type: "tool_call", tool: "web_search", input: "news" }),
        frame("step", { type: "tool_result", tool: "web_search", success: true, output: "- A: b (https://a.example)", ms: 120, links: [{ title: "A", url: "https://a.example" }] }),
        frame("token", { text: "Here." }),
        frame("message", { content: "Here.", sources: [], turn: { id: "t", user_message_id: 7, assistant_message_id: 8 } }),
      ]),
    );
    const { result } = renderHook(() => useChat({ getDocumentIds: () => null, onResetFailed: vi.fn() }));
    await act(() => result.current.send("news?"));
    const [user, bot] = result.current.messages;
    expect(bot.content).toBe("Here.");
    expect(bot.steps[0]).toMatchObject({ tool: "web_search", state: "done", input: "news", ms: 120, links: [{ title: "A", url: "https://a.example" }] });
    expect(user.serverId).toBe(7);
    expect(bot.serverId).toBe(8);
  });

  it("regenerate rewinds the server to the question, then asks it again", async () => {
    setFollowupsEnabled(false);
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (String(url) === "/chat/rewind") return new Response(JSON.stringify({ removed: 2 }), { status: 200 });
      return sseResponse([frame("message", { content: "answer", sources: [], turn: { id: "t", user_message_id: 11, assistant_message_id: 12 } })]);
    });
    const { result } = renderHook(() => useChat({ getDocumentIds: () => null, onResetFailed: vi.fn() }));
    await act(() => result.current.send("question"));
    const botId = result.current.messages[1].id;
    await act(async () => {
      await result.current.regenerate(botId);
    });
    const rewind = fetchMock.mock.calls.find((c) => String(c[0]) === "/chat/rewind")!;
    expect(JSON.parse(String((rewind[1] as RequestInit).body))).toEqual({ before_id: 11 });
    expect(result.current.messages.map((m) => m.content)).toEqual(["question", "answer"]);
    expect(result.current.messages[1].id).not.toBe(botId);
  });

  it("edit & resend rewinds and hands the text back", async () => {
    setFollowupsEnabled(false);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (String(url) === "/chat/rewind") return new Response(JSON.stringify({ removed: 2 }), { status: 200 });
      return sseResponse([frame("message", { content: "answer", sources: [], turn: { id: "t", user_message_id: 3, assistant_message_id: 4 } })]);
    });
    const { result } = renderHook(() => useChat({ getDocumentIds: () => null, onResetFailed: vi.fn() }));
    await act(() => result.current.send("typo questoin"));
    let text: string | null = null;
    await act(async () => {
      text = await result.current.editFrom(result.current.messages[0].id);
    });
    expect(text).toBe("typo questoin");
    expect(result.current.messages).toHaveLength(0);
  });

  it("restores the transcript the server remembers", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ messages: [
        { id: 1, role: "user", content: "hi there", meta: {} },
        { id: 2, role: "assistant", content: "hello", meta: { sources: [{ n: 1, document: "a.txt" }], tools: [{ tool: "search_documents", success: true }] } },
      ] }), { status: 200 }),
    );
    const { result } = renderHook(() => useChat({ getDocumentIds: () => null, onResetFailed: vi.fn() }));
    await act(() => result.current.restore());
    expect(result.current.messages.map((m) => [m.role, m.content, m.serverId])).toEqual([["user", "hi there", 1], ["assistant", "hello", 2]]);
    expect(result.current.messages[1]).toMatchObject({ prompt: "hi there", sources: [{ n: 1, document: "a.txt" }], steps: [{ tool: "search_documents", state: "done" }] });
  });

  it("asks for follow-ups after an answer when they're on", async () => {
    setFollowupsEnabled(true);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (String(url) === "/chat/followups") return new Response(JSON.stringify({ suggestions: ["More?", "Why?"] }), { status: 200 });
      return sseResponse([frame("message", { content: "answer", sources: [] })]);
    });
    const { result } = renderHook(() => useChat({ getDocumentIds: () => null, onResetFailed: vi.fn() }));
    await act(() => result.current.send("q"));
    await waitFor(() => expect(result.current.messages[1].followups).toEqual(["More?", "Why?"]));
  });
});
