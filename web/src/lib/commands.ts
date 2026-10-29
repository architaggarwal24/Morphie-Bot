// Composer shortcuts: "/calc" style commands force a tool; "@name" scopes a question to one document.

export interface SlashCommand {
  command: string;
  tool: "calculator" | "get_current_time" | "web_search" | "search_documents";
  label: string;
  hint: string;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { command: "calc", tool: "calculator", label: "Calculator", hint: "Work it out with the calculator" },
  { command: "time", tool: "get_current_time", label: "Clock", hint: "Check the time anywhere" },
  { command: "web", tool: "web_search", label: "Web search", hint: "Look it up on the web" },
  { command: "docs", tool: "search_documents", label: "Your documents", hint: "Answer from your uploads" },
];

export function commandForTool(tool: string | null | undefined): SlashCommand | undefined {
  return SLASH_COMMANDS.find((c) => c.tool === tool);
}

/** "/web latest news" -> { tool: "web_search", rest: "latest news" }; anything else -> null. */
export function parseLeadingCommand(text: string): { tool: SlashCommand["tool"]; rest: string } | null {
  const m = /^\/(\w+)(?:\s+|$)([\s\S]*)$/.exec(text.trimStart());
  if (!m) return null;
  const cmd = SLASH_COMMANDS.find((c) => c.command === m[1].toLowerCase());
  return cmd ? { tool: cmd.tool, rest: m[2] } : null;
}

export interface Trigger {
  kind: "slash" | "mention";
  query: string;
  start: number; // index of the "/" or "@"
  end: number; // caret
}

/** What the person is typing right before the caret: "/we" at the very start, or "@res" after a space. */
export function findTrigger(text: string, caret: number): Trigger | null {
  const before = text.slice(0, caret);
  const slash = /^\/(\w{0,12})$/.exec(before);
  if (slash) return { kind: "slash", query: slash[1].toLowerCase(), start: 0, end: caret };
  const mention = /(^|\s)@([^\s@]{0,40})$/.exec(before);
  if (mention) {
    const start = caret - mention[2].length - 1;
    return { kind: "mention", query: mention[2].toLowerCase(), start, end: caret };
  }
  return null;
}
