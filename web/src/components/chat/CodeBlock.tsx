import { AnimatePresence, motion } from "motion/react";
import { Check, Copy } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { copyText } from "@/lib/clipboard";

/** A fenced code block: a dark glass card with the language and a copy button that morphs into a check. */
export function CodeBlock({ children, language }: { children: ReactNode; language?: string }) {
  const ref = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);

  async function copy() {
    if (await copyText(ref.current?.innerText ?? "")) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    }
  }

  return (
    <div className="group/code relative my-3 overflow-hidden rounded-2xl border border-white/10 bg-[var(--code-bg)] shadow-[inset_0_1px_0_rgb(255_255_255/0.06)]">
      <div className="flex items-center gap-2 border-b border-white/[0.07] px-3.5 py-2 text-[11.5px] text-white/55">
        <span className="flex gap-1.5" aria-hidden="true">
          <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]/80" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]/80" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]/80" />
        </span>
        <span className="ml-1.5 font-mono tracking-wide uppercase">{language || "code"}</span>
        <button
          type="button"
          onClick={copy}
          aria-label={copied ? "Copied" : "Copy code"}
          className="ml-auto flex items-center gap-1.5 rounded-md px-2 py-1 text-white/60 transition hover:bg-white/10 hover:text-white"
        >
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={copied ? "y" : "n"}
              initial={{ scale: 0.5, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.5, opacity: 0 }}
              transition={{ type: "spring", stiffness: 600, damping: 30 }}
              className="flex items-center gap-1.5"
            >
              {copied ? <Check size={13} className="text-emerald-400" aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
              {copied ? "Copied" : "Copy"}
            </motion.span>
          </AnimatePresence>
        </button>
      </div>
      <pre ref={ref} className="scrollbar-thin overflow-x-auto p-4 font-mono text-[13px] leading-6 text-[#e4e1f7]">
        {children}
      </pre>
    </div>
  );
}
