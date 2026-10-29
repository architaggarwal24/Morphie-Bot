import { AnimatePresence, motion } from "motion/react";
import { FileText } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import type { Source } from "@/hooks/useChat";
import { cn } from "@/lib/cn";

/** A citation trigger (inline [n] or a source chip) that opens a glass card with the matched passage. */
export function SourcePopover({ source, children, className, label }: { source: Source; children: ReactNode; className?: string; label: string }) {
  const [open, setOpen] = useState(false);
  const hover = useRef(0);
  const wrap = useRef<HTMLSpanElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  return (
    <span
      ref={wrap}
      className="relative inline-flex"
      onMouseEnter={() => {
        window.clearTimeout(hover.current);
        hover.current = window.setTimeout(() => setOpen(true), 250);
      }}
      onMouseLeave={() => {
        window.clearTimeout(hover.current);
        hover.current = window.setTimeout(() => setOpen(false), 200);
      }}
    >
      <button type="button" aria-label={label} aria-expanded={open} aria-describedby={open ? id : undefined} onClick={() => setOpen((o) => !o)} className={className}>
        {children}
      </button>
      <AnimatePresence>
        {open && (
          <motion.span
            id={id}
            role="tooltip"
            initial={{ opacity: 0, y: 6, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.97, transition: { duration: 0.12 } }}
            transition={{ type: "spring", stiffness: 520, damping: 32 }}
            className="glass-strong absolute bottom-full left-0 z-40 mb-2 block w-[min(340px,80vw)] rounded-2xl p-3.5 text-left text-[12.5px] leading-relaxed font-normal text-muted"
          >
            <span className="mb-1.5 flex items-center gap-2 text-[12.5px] font-semibold text-fg">
              <span className="grid h-5 min-w-5 place-items-center rounded-md bg-pink/15 px-1 text-[11px] text-pink">{source.n ?? "•"}</span>
              <FileText size={13} className="shrink-0 text-pink" aria-hidden="true" />
              <span className="truncate">{source.document}</span>
              {source.page != null && <span className="shrink-0 font-normal text-subtle">p.{source.page}</span>}
            </span>
            <span className={cn("block whitespace-pre-wrap", !source.snippet && "italic")}>{source.snippet ? `“${source.snippet}”` : "Matched passage not available."}</span>
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}
