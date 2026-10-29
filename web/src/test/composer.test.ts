import { describe, expect, it } from "vitest";
import { findTrigger, parseLeadingCommand } from "@/lib/commands";
import rehypeCitations from "@/lib/rehypeCitations";
import { toMarkdown } from "@/lib/exportChat";
import type { Message } from "@/hooks/useChat";

describe("composer commands", () => {
  it("reads a leading /command", () => {
    expect(parseLeadingCommand("/web latest AI news")).toEqual({ tool: "web_search", rest: "latest AI news" });
    expect(parseLeadingCommand("/calc")).toEqual({ tool: "calculator", rest: "" });
    expect(parseLeadingCommand("/nope hi")).toBeNull();
    expect(parseLeadingCommand("what is 1/2")).toBeNull();
  });

  it("finds what is being typed before the caret", () => {
    expect(findTrigger("/we", 3)).toEqual({ kind: "slash", query: "we", start: 0, end: 3 });
    expect(findTrigger("hi /we", 6)).toBeNull(); // commands only at the start
    expect(findTrigger("what does @res", 14)).toEqual({ kind: "mention", query: "res", start: 10, end: 14 });
    expect(findTrigger("email me@home", 13)).toBeNull(); // an address, not a mention
  });
});

describe("citations", () => {
  it("turns only real source numbers into citation marks, never inside code", () => {
    const tree: any = {
      type: "root",
      children: [
        { type: "element", tagName: "p", children: [{ type: "text", value: "Five years [1] and arrays[2] and [9]." }] },
        { type: "element", tagName: "code", children: [{ type: "text", value: "x[1]" }] },
      ],
    };
    (rehypeCitations({ valid: [1, 2] }) as any)(tree);
    const p = tree.children[0].children;
    expect(p.filter((n: any) => n.tagName === "sup").map((n: any) => n.properties.dataN)).toEqual(["1", "2"]);
    expect(p.map((n: any) => n.value ?? `<${n.properties.dataN}>`).join("")).toBe("Five years <1> and arrays<2> and [9].");
    expect(tree.children[1].children[0].value).toBe("x[1]");
  });
});

describe("export", () => {
  it("writes the conversation as Markdown with tools and sources", () => {
    const messages: Message[] = [
      { id: "a", role: "user", content: "What about Python?", status: "done", steps: [], thinking: false, sources: [] },
      {
        id: "b", role: "assistant", content: "Five years [1].", status: "done", thinking: false,
        steps: [{ id: 1, tool: "search_documents", state: "done" }], sources: [{ n: 1, document: "cv.pdf", page: 2 }],
      },
    ];
    const md = toMarkdown(messages);
    expect(md).toContain("## You\n\nWhat about Python?");
    expect(md).toContain("> Tools: Docs");
    expect(md).toContain("[1] cv.pdf, p.2");
  });
});
