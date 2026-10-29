// Export the conversation: Markdown file, clipboard, or the browser's print dialog (Save as PDF).
import type { Message } from "@/hooks/useChat";
import { toolMeta } from "./tools";

export function toMarkdown(messages: Message[], title = "Morphie conversation"): string {
  const lines = [`# ${title}`, "", `_Exported ${new Date().toLocaleString()}_`, ""];
  for (const m of messages) {
    if (m.role === "user") {
      lines.push("## You", "", m.content, "");
      continue;
    }
    lines.push("## Morphie", "");
    if (m.steps.length) lines.push(`> Tools: ${m.steps.map((s) => toolMeta(s.tool).name).join(", ")}`, "");
    if (m.content) lines.push(m.content, "");
    if (m.error) lines.push(`> ⚠️ ${m.error}`, "");
    if (m.status === "stopped") lines.push("_(stopped)_", "");
    if (m.sources.length) {
      lines.push("**Sources**", "");
      for (const s of m.sources) lines.push(`${s.n ? `[${s.n}] ` : "- "}${s.document}${s.page != null ? `, p.${s.page}` : ""}`);
      lines.push("");
    }
  }
  return lines.join("\n").trim() + "\n";
}

export function downloadText(filename: string, text: string, type = "text/markdown") {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function exportFilename(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `morphie-chat-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}.md`;
}
