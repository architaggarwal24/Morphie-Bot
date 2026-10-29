import { motion } from "motion/react";
import { cn } from "@/lib/cn";

interface SwitchProps {
  id: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  className?: string;
}

/** A real checkbox (role="switch") with an animated track and knob. */
export function Switch({ id, label, checked, onChange, className }: SwitchProps) {
  return (
    <label htmlFor={id} className={cn("flex min-h-11 items-center justify-between gap-3 rounded-xl px-1 text-sm text-fg", className)}>
      <span>{label}</span>
      <span className="relative inline-flex">
        <input
          id={id}
          type="checkbox"
          role="switch"
          aria-checked={checked}
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="peer absolute inset-0 z-10 cursor-pointer opacity-0"
        />
        <span
          aria-hidden="true"
          className={cn(
            "flex h-6 w-11 items-center rounded-full border p-0.5 transition-colors duration-300 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ring",
            checked
              ? "justify-end border-primary/40 bg-[linear-gradient(135deg,var(--primary),var(--indigo))] shadow-glow"
              : "justify-start border-line-strong bg-surface-2",
          )}
        >
          <motion.span layout transition={{ type: "spring", stiffness: 600, damping: 32 }} className="h-[18px] w-[18px] rounded-full bg-white shadow-md" />
        </span>
      </span>
    </label>
  );
}
