import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/cn";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  id: string;
  labelledBy?: string;
  label?: string;
  children: ReactNode;
  className?: string;
  /** Where the card sits: centered (dialogs) or near the top (command menu). */
  placement?: "center" | "top";
  overlayClassName?: string;
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** A glass dialog: blurred backdrop, spring-in card, Tab kept inside, Escape closes, focus returns on close. */
export function Modal({ open, onClose, id, labelledBy, label, children, className, placement = "center", overlayClassName }: ModalProps) {
  const card = useRef<HTMLDivElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    returnTo.current = document.activeElement as HTMLElement | null;
    return () => {
      const el = returnTo.current;
      if (el && typeof el.focus === "function" && document.contains(el)) requestAnimationFrame(() => el.focus());
    };
  }, [open]);

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !card.current) return;
    const items = Array.from(card.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((n) => n.offsetParent !== null || n === document.activeElement);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          id={id}
          role="dialog"
          aria-modal="true"
          aria-labelledby={labelledBy}
          aria-label={label}
          className={cn(
            "mp-modal fixed inset-0 z-[70] flex justify-center bg-black/45 p-4 backdrop-blur-md light:bg-[rgb(40_30_90/0.18)]",
            placement === "center" ? "items-center" : "items-start pt-[12vh]",
            overlayClassName,
          )}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.18 } }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) onClose();
          }}
          onKeyDown={onKeyDown}
        >
          <motion.div
            ref={card}
            className={cn("glass-strong gradient-border relative w-full rounded-3xl", className)}
            initial={{ opacity: 0, scale: 0.94, y: placement === "top" ? -12 : 16, filter: "blur(8px)" }}
            animate={{ opacity: 1, scale: 1, y: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, scale: 0.96, y: 8, filter: "blur(4px)", transition: { duration: 0.15 } }}
            transition={{ type: "spring", stiffness: 420, damping: 32 }}
          >
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
