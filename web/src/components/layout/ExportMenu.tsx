import { AnimatePresence, motion } from "motion/react";
import { ClipboardCopy, FileDown, Printer, Share } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Tooltip } from "@/components/ui/Tooltip";
import { cn } from "@/lib/cn";

interface Props {
  disabled: boolean;
  onMarkdown: () => void;
  onCopy: () => void;
  onPrint: () => void;
}

/** Export the conversation: Markdown file, clipboard, or Print / Save as PDF. */
export function ExportMenu({ disabled, onMarkdown, onCopy, onPrint }: Props) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);

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

  const items = [
    { label: "Download as Markdown", icon: FileDown, run: onMarkdown },
    { label: "Copy conversation", icon: ClipboardCopy, run: onCopy },
    { label: "Print / save as PDF", icon: Printer, run: onPrint },
  ];

  return (
    <div ref={wrap} className="relative">
      <Tooltip label="Export chat" side="bottom">
        <button
          type="button"
          aria-label="Export chat"
          aria-haspopup="menu"
          aria-expanded={open}
          disabled={disabled}
          onClick={() => setOpen((o) => !o)}
          className={cn(
            "grid h-10 w-10 place-items-center rounded-xl border transition disabled:opacity-40",
            open ? "border-primary/40 bg-primary-soft text-primary" : "border-transparent text-muted hover:bg-surface-2 hover:text-fg",
          )}
        >
          <Share size={17} aria-hidden="true" />
        </button>
      </Tooltip>
      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={{ opacity: 0, y: -6, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, transition: { duration: 0.12 } }}
            transition={{ type: "spring", stiffness: 520, damping: 32 }}
            className="glass-strong absolute top-full right-0 z-50 mt-2 w-56 origin-top-right rounded-2xl p-1.5"
          >
            {items.map((item, i) => (
              <motion.button
                key={item.label}
                role="menuitem"
                type="button"
                autoFocus={i === 0}
                initial={{ opacity: 0, x: 6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.04 }}
                onClick={() => {
                  setOpen(false);
                  item.run();
                }}
                className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-[13.5px] text-muted transition hover:bg-primary-soft hover:text-fg focus-visible:bg-primary-soft focus-visible:text-fg"
              >
                <item.icon size={15} aria-hidden="true" />
                {item.label}
              </motion.button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
