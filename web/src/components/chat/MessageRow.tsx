import { AnimatePresence, motion } from "motion/react";
import { ArrowUpRight, Check, Copy, FileText, Pencil, RefreshCw, RotateCcw, Square, TriangleAlert } from "lucide-react";
import { Suspense, lazy, memo, useState, type ReactNode } from "react";
import { Orb } from "@/components/fx/Orb";
import { Tooltip } from "@/components/ui/Tooltip";
import { useToast } from "@/components/ui/Toast";
import type { Message } from "@/hooks/useChat";
import { copyText } from "@/lib/clipboard";
import { cn } from "@/lib/cn";
import { AgentTimeline } from "./AgentTimeline";
import { SourcePopover } from "./SourcePopover";
// The markdown + syntax-highlighting stack is the biggest piece of the app: it loads after first paint.
const loadMarkdown = () => import("./Markdown");
const Markdown = lazy(loadMarkdown);
if (typeof window !== "undefined") {
  const idle = (window as any).requestIdleCallback ?? ((fn: () => void) => window.setTimeout(fn, 1200));
  idle(() => loadMarkdown());
}

function ActionButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <Tooltip label={label} side="bottom">
      <motion.button
        type="button"
        aria-label={label}
        onClick={onClick}
        whileHover={{ scale: 1.08 }}
        whileTap={{ scale: 0.88 }}
        className="grid h-8 w-8 place-items-center rounded-lg text-subtle transition-colors hover:bg-surface-2 hover:text-fg"
      >
        {children}
      </motion.button>
    </Tooltip>
  );
}

function CopyAction({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  const showToast = useToast();
  return (
    <ActionButton
      label={done ? "Copied" : "Copy"}
      onClick={async () => {
        if (await copyText(text)) {
          setDone(true);
          window.setTimeout(() => setDone(false), 1500);
        } else showToast("Couldn't copy. Select the text and copy it instead.", { tone: "error" });
      }}
    >
      <AnimatePresence mode="wait" initial={false}>
        <motion.span key={done ? "y" : "n"} initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.4, opacity: 0 }}>
          {done ? <Check size={15} className="text-success" aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
        </motion.span>
      </AnimatePresence>
    </ActionButton>
  );
}

const enter = {
  initial: { opacity: 0, y: 14, filter: "blur(6px)" },
  animate: { opacity: 1, y: 0, filter: "blur(0px)" },
  transition: { type: "spring" as const, stiffness: 320, damping: 30 },
};

interface Props {
  message: Message;
  busy: boolean;
  onRegenerate: (id: string) => void;
  onEdit: (id: string) => void;
  onFollowup: (text: string) => void;
}

export const MessageRow = memo(function MessageRow({ message: m, busy, onRegenerate, onEdit, onFollowup }: Props) {
  if (m.role === "user") {
    return (
      <motion.div {...enter} className="mp-row mp-row--user group flex flex-col items-end">
        <div className="mp-bubble mp-bubble--user max-w-[85%] rounded-[20px] rounded-br-md border border-primary/30 bg-[linear-gradient(135deg,rgb(139_92_246/0.32),rgb(99_102_241/0.22))] px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-fg shadow-[inset_0_1px_0_rgb(255_255_255/0.12),0_8px_24px_-12px_rgb(124_58_237/0.6)] backdrop-blur-md light:bg-[linear-gradient(135deg,rgb(124_58_237/0.14),rgb(79_70_229/0.10))]">
          {m.content}
        </div>
        <div className="msg-actions mt-1 flex gap-0.5 opacity-0 transition-opacity duration-200 group-focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100">
          <CopyAction text={m.content} />
          {!busy && (
            <ActionButton label="Edit & resend" onClick={() => onEdit(m.id)}>
              <Pencil size={14} aria-hidden="true" />
            </ActionButton>
          )}
        </div>
      </motion.div>
    );
  }

  const live = m.status === "streaming";
  return (
    <motion.div {...enter} className="mp-row group flex gap-3 sm:gap-4">
      <div className="mp-avatar mp-avatar--assistant pt-0.5">
        <Orb size={30} busy={live} />
      </div>
      <div className="mp-bubble-col min-w-0 flex-1">
        <AgentTimeline steps={m.steps} thinking={m.thinking} live={live} />

        {(m.content || (live && !m.thinking && !m.steps.some((s) => s.state === "active"))) && (
          <div className={cn("mp-bubble mp-bubble--assistant", live && "is-streaming")}>
            <Suspense fallback={<div className="prose-morphie whitespace-pre-wrap">{m.content}</div>}>
              <Markdown text={m.content} streaming={live} sources={m.sources} />
            </Suspense>
          </div>
        )}

        {m.status === "error" && m.error && (
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1, x: [0, -5, 5, -3, 3, 0] }}
            transition={{ duration: 0.45 }}
            role="alert"
            className="mp-bubble mp-bubble--error mt-2 flex items-start gap-3 rounded-2xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-fg"
          >
            <TriangleAlert size={17} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />
            <span className="flex-1">{m.error}</span>
            {m.prompt && !busy && (
              <button type="button" onClick={() => onRegenerate(m.id)} className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[13px] font-semibold text-danger transition hover:bg-danger/10">
                <RotateCcw size={13} aria-hidden="true" /> Retry
              </button>
            )}
          </motion.div>
        )}

        {m.status === "stopped" && (
          <div className="mp-meta-row mt-2">
            <span className="mp-chip inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1 text-[12px] text-muted" title="Morphie won't remember this answer">
              <Square size={10} fill="currentColor" aria-hidden="true" /> Stopped · not remembered
            </span>
          </div>
        )}

        {m.sources.length > 0 && (
          <div className="mt-3">
            <div className="mp-hint mb-1.5 text-[11px] font-semibold tracking-[0.12em] text-subtle uppercase">Sources</div>
            <div className="mp-meta-row flex flex-wrap gap-1.5">
              {m.sources.map((s, i) => (
                <motion.span
                  key={`${s.document}-${s.page}-${i}`}
                  initial={{ opacity: 0, y: 6, scale: 0.9 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  transition={{ delay: 0.1 + i * 0.06, type: "spring", stiffness: 400, damping: 26 }}
                >
                  <SourcePopover
                    source={s}
                    label={`Show the passage from ${s.document}${s.page != null ? `, page ${s.page}` : ""}`}
                    className="mp-chip mp-chip--source inline-flex items-center gap-1.5 rounded-full border border-pink/30 bg-pink/10 px-2.5 py-1 text-[12px] font-medium text-fg transition hover:border-pink/60 hover:bg-pink/20"
                  >
                    {s.n != null && <span className="grid h-4 min-w-4 place-items-center rounded bg-pink/20 px-0.5 text-[10px] font-bold text-pink">{s.n}</span>}
                    <FileText size={12} className="text-pink" aria-hidden="true" />
                    {s.page != null ? `${s.document} · p.${s.page}` : s.document}
                  </SourcePopover>
                </motion.span>
              ))}
            </div>
          </div>
        )}

        {!live && (m.content || m.status === "stopped") && (
          <div className={cn("msg-actions mt-1.5 -ml-1.5 flex gap-0.5 opacity-0 transition-opacity duration-200 group-focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100")}>
            {m.content && <CopyAction text={m.content} />}
            {m.prompt && !busy && (
              <ActionButton label="Regenerate" onClick={() => onRegenerate(m.id)}>
                <RefreshCw size={15} aria-hidden="true" />
              </ActionButton>
            )}
          </div>
        )}

        {m.followups && m.followups.length > 0 && !busy && (
          <div className="msg-actions mt-3 flex flex-wrap gap-2" aria-label="Suggested follow-ups">
            {m.followups.map((f, i) => (
              <motion.button
                key={f}
                type="button"
                onClick={() => onFollowup(f)}
                initial={{ opacity: 0, y: 8, filter: "blur(4px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                transition={{ delay: i * 0.08, type: "spring", stiffness: 380, damping: 28 }}
                whileHover={{ y: -2 }}
                whileTap={{ scale: 0.97 }}
                className="followup group flex items-center gap-1.5 rounded-full border border-primary/25 bg-primary-soft px-3 py-1.5 text-left text-[12.5px] text-fg transition-colors hover:border-primary/50"
              >
                {f}
                <ArrowUpRight size={13} className="text-primary transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" aria-hidden="true" />
              </motion.button>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
});
