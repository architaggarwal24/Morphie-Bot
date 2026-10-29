import { motion } from "motion/react";
import { cn } from "@/lib/cn";

/** Headline that blurs in word by word. */
export function BlurText({ text, className, delay = 0, wordClassName }: { text: string; className?: string; delay?: number; wordClassName?: string }) {
  const words = text.split(" ");
  return (
    <span className={cn("inline-block", className)} aria-label={text}>
      {words.map((w, i) => (
        <motion.span
          key={i + w}
          aria-hidden="true"
          className={cn("inline-block will-change-[filter,transform]", wordClassName)}
          initial={{ opacity: 0, filter: "blur(10px)", y: 12 }}
          animate={{ opacity: 1, filter: "blur(0px)", y: 0 }}
          transition={{ duration: 0.7, delay: delay + i * 0.08, ease: [0.22, 1, 0.36, 1] }}
        >
          {w}
          {i < words.length - 1 ? " " : ""}
        </motion.span>
      ))}
    </span>
  );
}
