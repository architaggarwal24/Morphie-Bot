import { describe, expect, it } from "vitest";
import { parseFrame, readSse } from "@/lib/api";
import { LLM_KEY, clearLlm, isRemembered, llmHeaders, loadLlm, saveLlm, withLlmHeaders } from "@/lib/llm";
import { SHORTCUTS, formatShortcut, isTypingTarget, matchesShortcut, withHint } from "@/lib/shortcuts";
import rehypeWords from "@/lib/rehypeWords";
import { filterCommands, type CommandAction } from "@/components/dialogs/CommandMenu";
import { Plus } from "lucide-react";

describe("SSE parsing", () => {
  it("reads the event name and JSON data of a frame", () => {
    expect(parseFrame('event: token\ndata: {"text":"hi"}')).toEqual({ event: "token", data: { text: "hi" } });
    expect(parseFrame("data: not json").data).toBeNull();
  });

  it("splits a stream into frames even when chunks cut them in half", async () => {
    const enc = new TextEncoder();
    const parts = ['event: step\ndata: {"type":"thi', 'nking"}\n\nevent: token\nda', 'ta: {"text":"a"}\n\n'];
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        parts.forEach((p) => c.enqueue(enc.encode(p)));
        c.close();
      },
    });
    const seen: string[] = [];
    await readSse(body, (f) => seen.push(f.event + ":" + JSON.stringify(f.data)));
    expect(seen).toEqual(['step:{"type":"thinking"}', 'token:{"text":"a"}']);
  });
});

describe("bring your own key", () => {
  it("sends nothing when no choice is saved", () => {
    expect(llmHeaders()).toEqual({});
  });

  it("carries the saved choice as X-LLM-* headers", () => {
    saveLlm({ provider: "openai", model: "gpt-4o", key: "sk-test-123456" }, true);
    expect(withLlmHeaders({ "Content-Type": "application/json" })).toEqual({
      "Content-Type": "application/json",
      "X-LLM-Provider": "openai",
      "X-LLM-Model": "gpt-4o",
      "X-LLM-Key": "sk-test-123456",
    });
  });

  it("remembers on this device only when asked, otherwise until the tab closes", () => {
    saveLlm({ provider: "mistral", model: "", key: "abcdefgh12" }, false);
    expect(localStorage.getItem(LLM_KEY)).toBeNull();
    expect(sessionStorage.getItem(LLM_KEY)).not.toBeNull();
    expect(isRemembered()).toBe(false);
    saveLlm({ provider: "mistral", model: "", key: "abcdefgh12" }, true);
    expect(sessionStorage.getItem(LLM_KEY)).toBeNull();
    expect(isRemembered()).toBe(true);
    clearLlm();
    expect(loadLlm()).toBeNull();
  });

  it("treats unreadable storage as nothing saved", () => {
    localStorage.setItem(LLM_KEY, "{not json");
    expect(loadLlm()).toBeNull();
  });
});

describe("shortcuts", () => {
  it("names the platform modifier", () => {
    expect(formatShortcut(SHORTCUTS.commandMenu, true)).toBe("⌘K");
    expect(formatShortcut(SHORTCUTS.newChat, true)).toBe("⌘⇧O");
    expect(formatShortcut(SHORTCUTS.commandMenu, false)).toBe("Ctrl+K");
    expect(formatShortcut(SHORTCUTS.newChat, false)).toBe("Ctrl+Shift+O");
  });

  it("matches only the exact chord", () => {
    const ev = (init: KeyboardEventInit) => new KeyboardEvent("keydown", init);
    expect(matchesShortcut(ev({ key: "k", ctrlKey: true }), SHORTCUTS.commandMenu, false)).toBe(true);
    expect(matchesShortcut(ev({ key: "k", metaKey: true }), SHORTCUTS.commandMenu, true)).toBe(true);
    expect(matchesShortcut(ev({ key: "k" }), SHORTCUTS.commandMenu, false)).toBe(false);
    expect(matchesShortcut(ev({ key: "k", ctrlKey: true, altKey: true }), SHORTCUTS.commandMenu, false)).toBe(false);
    expect(matchesShortcut(ev({ key: "O", ctrlKey: true, shiftKey: true }), SHORTCUTS.newChat, false)).toBe(true);
  });

  it("knows when someone is typing", () => {
    const text = document.createElement("textarea");
    const box = document.createElement("input");
    box.type = "checkbox";
    expect(isTypingTarget(text)).toBe(true);
    expect(isTypingTarget(box)).toBe(false);
    expect(isTypingTarget(document.body)).toBe(false);
  });

  it("adds the shortcut to tooltips", () => {
    expect(withHint("Search", "commandMenu")).toMatch(/^Search \((⌘K|Ctrl\+K)\)$/);
  });
});

describe("command filtering", () => {
  const a = (label: string, keywords = ""): CommandAction => ({ id: label, label, keywords, icon: Plus, group: "Actions", run() {} });
  const all = [a("Go to chat"), a("Open documents", "files"), a("Upload a document", "pdf")];

  it("needs every word, in the label or keywords", () => {
    expect(filterCommands(all, "pdf").map((x) => x.label)).toEqual(["Upload a document"]);
    expect(filterCommands(all, "doc open").map((x) => x.label)).toEqual(["Open documents"]);
    expect(filterCommands(all, "zzz")).toEqual([]);
  });

  it("sorts label-prefix matches first", () => {
    expect(filterCommands(all, "up")[0].label).toBe("Upload a document");
  });
});

describe("streaming word reveal", () => {
  it("wraps words in spans but leaves code alone", () => {
    const tree: any = {
      type: "root",
      children: [
        { type: "element", tagName: "p", children: [{ type: "text", value: "hello big world" }] },
        { type: "element", tagName: "pre", children: [{ type: "element", tagName: "code", children: [{ type: "text", value: "x = 1" }] }] },
      ],
    };
    (rehypeWords() as any)(tree);
    const p = tree.children[0].children;
    expect(p.filter((n: any) => n.tagName === "span").map((n: any) => n.children[0].value)).toEqual(["hello", "big", "world"]);
    expect(tree.children[1].children[0].children[0]).toEqual({ type: "text", value: "x = 1" });
  });
});
