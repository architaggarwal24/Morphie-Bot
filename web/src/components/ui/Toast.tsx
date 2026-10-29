import { AnimatePresence, motion } from "motion/react";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { CircleCheck, Info, TriangleAlert, X } from "lucide-react";
import { cn } from "@/lib/cn";

export const UNDO_MS = 6000; // how long an Undo toast (and the delayed request behind it) lasts

type Tone = "info" | "success" | "error";

export interface ToastOptions {
  action?: { label: string; onClick: () => void };
  duration?: number;
  tone?: Tone;
}

interface ToastItem extends ToastOptions {
  id: number;
  message: string;
}

export interface ToastHandle {
  dismiss: () => void;
}

type ShowToast = (message: string, options?: ToastOptions) => ToastHandle;

const ToastContext = createContext<ShowToast>(() => ({ dismiss() {} }));

export const useToast = () => useContext(ToastContext);

const ICONS = { info: Info, success: CircleCheck, error: TriangleAlert } as const;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    window.clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback<ShowToast>(
    (message, options = {}) => {
      const id = nextId.current++;
      setToasts((list) => [...list.slice(-3), { id, message, ...options }]);
      timers.current.set(id, window.setTimeout(() => dismiss(id), options.duration ?? 4500));
      return { dismiss: () => dismiss(id) };
    },
    [dismiss],
  );

  const value = useMemo(() => showToast, [showToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* role="status": screen readers announce politely, without stealing focus */}
      <div className="toast-stack pointer-events-none fixed inset-x-0 top-3 z-[80] flex flex-col items-center gap-2 px-3 sm:top-auto sm:right-6 sm:bottom-6 sm:left-auto sm:items-end sm:px-0" role="status" aria-live="polite">
        <AnimatePresence initial={false}>
          {toasts.map((t) => {
            const Icon = ICONS[t.tone ?? "info"];
            return (
              <motion.div
                key={t.id}
                layout
                drag="x"
                dragConstraints={{ left: 0, right: 0 }}
                dragElastic={0.6}
                onDragEnd={(_, info) => {
                  if (Math.abs(info.offset.x) > 90) dismiss(t.id);
                }}
                initial={{ opacity: 0, y: 24, x: 0, scale: 0.92, filter: "blur(6px)" }}
                animate={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)" }}
                exit={{ opacity: 0, scale: 0.9, y: 8, transition: { duration: 0.18 } }}
                transition={{ type: "spring", stiffness: 420, damping: 30 }}
                className="toast glass-strong pointer-events-auto flex w-full max-w-sm items-center gap-3 rounded-2xl py-2.5 pr-2 pl-3.5 text-sm text-fg"
              >
                <Icon
                  size={17}
                  aria-hidden="true"
                  className={cn("shrink-0", t.tone === "error" ? "text-danger" : t.tone === "success" ? "text-success" : "text-primary")}
                />
                <span className="toast__text min-w-0 flex-1">{t.message}</span>
                {t.action && (
                  <button
                    type="button"
                    className="toast__action rounded-lg px-2.5 py-1.5 text-[13px] font-semibold text-primary transition hover:bg-primary-soft"
                    onClick={() => {
                      dismiss(t.id);
                      t.action!.onClick();
                    }}
                  >
                    {t.action.label}
                  </button>
                )}
                <button
                  type="button"
                  aria-label="Dismiss"
                  className="grid h-7 w-7 place-items-center rounded-lg text-subtle transition hover:bg-surface-2 hover:text-fg"
                  onClick={() => dismiss(t.id)}
                >
                  <X size={14} aria-hidden="true" />
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}
