// A tiny rehype plugin used only while a reply streams: it wraps each word of text in <span class="word-in">.
// react-markdown keys siblings by tag name + index, so words already on screen keep their DOM node and only
// newly-arrived words mount - and the CSS animation on .word-in plays just for them (a blur-in "reveal").

type Node = { type: string; tagName?: string; value?: string; children?: Node[]; properties?: Record<string, unknown> };

const SKIP = new Set(["pre", "code"]);

function wrap(node: Node) {
  if (!node.children) return;
  const out: Node[] = [];
  for (const child of node.children) {
    if (child.type === "text" && child.value) {
      for (const part of child.value.split(/(\s+)/)) {
        if (!part) continue;
        if (/^\s+$/.test(part)) out.push({ type: "text", value: part });
        else out.push({ type: "element", tagName: "span", properties: { className: ["word-in"] }, children: [{ type: "text", value: part }] });
      }
    } else {
      if (child.type === "element" && !SKIP.has(child.tagName ?? "")) wrap(child);
      out.push(child);
    }
  }
  node.children = out;
}

export default function rehypeWords() {
  return (tree: Node) => wrap(tree);
}
