import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Side = "top" | "bottom" | "right" | "left";

const POS: Record<Side, string> = {
  top: "bottom-full left-1/2 mb-2 -translate-x-1/2 translate-y-1 group-hover/tip:translate-y-0 group-focus-within/tip:translate-y-0",
  bottom: "top-full left-1/2 mt-2 -translate-x-1/2 -translate-y-1 group-hover/tip:translate-y-0 group-focus-within/tip:translate-y-0",
  right: "left-full top-1/2 ml-2 -translate-y-1/2 -translate-x-1 group-hover/tip:translate-x-0 group-focus-within/tip:translate-x-0",
  left: "right-full top-1/2 mr-2 -translate-y-1/2 translate-x-1 group-hover/tip:translate-x-0 group-focus-within/tip:translate-x-0",
};

/** A small glass tooltip on hover / keyboard focus. Decorative only: the control keeps its own aria-label. */
export function Tooltip({ label, side = "top", children, className }: { label: ReactNode; side?: Side; children: ReactNode; className?: string }) {
  return (
    <span className={cn("group/tip relative inline-flex", className)}>
      {children}
      <span
        role="presentation"
        aria-hidden="true"
        className={cn(
          "glass-strong pointer-events-none absolute z-50 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-xs font-medium text-fg opacity-0 transition-all delay-0 duration-200 ease-[var(--ease-spring)] group-hover/tip:opacity-100 group-hover/tip:delay-300 group-focus-within/tip:opacity-100",
          POS[side],
        )}
      >
        {label}
      </span>
    </span>
  );
}
