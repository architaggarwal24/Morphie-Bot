import { motion, type HTMLMotionProps } from "motion/react";
import { forwardRef } from "react";
import { cn } from "@/lib/cn";
import { ripple } from "@/hooks/useEffects";

type Variant = "primary" | "soft" | "ghost" | "danger" | "outline";
type Size = "sm" | "md" | "lg" | "icon" | "icon-sm";

const VARIANTS: Record<Variant, string> = {
  primary:
    "shine text-on-primary bg-[linear-gradient(135deg,var(--primary)_0%,var(--indigo)_100%)] shadow-glow hover:brightness-110 border border-white/10",
  soft: "bg-surface-2 text-fg border border-line hover:bg-surface-3 hover:border-line-strong",
  ghost: "text-muted hover:text-fg hover:bg-surface-2 border border-transparent",
  outline: "text-fg border border-line-strong hover:bg-surface-2 hover:border-primary/50",
  danger: "text-danger border border-danger/30 bg-danger-soft hover:bg-danger/15 hover:border-danger/50",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5 rounded-lg",
  md: "h-10 px-4 text-sm gap-2 rounded-xl",
  lg: "h-12 px-5 text-[15px] gap-2 rounded-2xl",
  icon: "h-10 w-10 rounded-xl",
  "icon-sm": "h-8 w-8 rounded-lg",
};

export interface ButtonProps extends HTMLMotionProps<"button"> {
  variant?: Variant;
  size?: Size;
  block?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "soft", size = "md", block, className, onPointerDown, type = "button", children, ...rest },
  ref,
) {
  return (
    <motion.button
      ref={ref}
      type={type}
      whileHover={rest.disabled ? undefined : { y: -1 }}
      whileTap={rest.disabled ? undefined : { scale: 0.96 }}
      transition={{ type: "spring", stiffness: 500, damping: 30 }}
      onPointerDown={(e) => {
        if (!rest.disabled) ripple(e);
        onPointerDown?.(e);
      }}
      className={cn(
        "relative inline-flex select-none items-center justify-center overflow-hidden font-medium whitespace-nowrap transition-[background,border-color,color,filter,box-shadow] duration-200 disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        block && "w-full",
        className,
      )}
      {...rest}
    >
      {children}
    </motion.button>
  );
});
