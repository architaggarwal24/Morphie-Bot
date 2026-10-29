// Turns "[1]"-style citations in an answer into <sup class="cite" data-n="1"> - but only numbers that match a
// real source from this turn (so "[2]" in ordinary prose or code is left alone).

type Node = { type: string; tagName?: string; value?: string; children?: Node[]; properties?: Record<string, unknown> };

const SKIP = new Set(["pre", "code", "a"]);
const CITE = /\[(\d{1,2})\]/g;

export default function rehypeCitations(options: { valid: number[] }) {
  const valid = new Set(options?.valid ?? []);
  function walk(node: Node) {
    if (!node.children) return;
    const out: Node[] = [];
    for (const child of node.children) {
      if (child.type === "text" && child.value && valid.size) {
        let last = 0;
        const text = child.value;
        for (const m of text.matchAll(CITE)) {
          const n = Number(m[1]);
          if (!valid.has(n)) continue;
          if (m.index! > last) out.push({ type: "text", value: text.slice(last, m.index) });
          out.push({ type: "element", tagName: "sup", properties: { className: ["cite"], dataN: String(n) }, children: [{ type: "text", value: String(n) }] });
          last = m.index! + m[0].length;
        }
        if (last === 0) out.push(child);
        else if (last < text.length) out.push({ type: "text", value: text.slice(last) });
      } else {
        if (child.type === "element" && !SKIP.has(child.tagName ?? "")) walk(child);
        out.push(child);
      }
    }
    node.children = out;
  }
  return (tree: Node) => walk(tree);
}
