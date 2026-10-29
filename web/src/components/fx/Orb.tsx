import { motion, useMotionValue, useSpring, useTransform } from "motion/react";
import type { PointerEvent } from "react";
import { cn } from "@/lib/cn";

interface OrbProps {
  size?: number;
  busy?: boolean;
  /** Tilt toward the pointer (hero only). */
  interactive?: boolean;
  className?: string;
}

/** Morphie's mark: a morphing, swirling gradient orb. Spins faster while Morphie is working. */
export function Orb({ size = 28, busy = false, interactive = false, className }: OrbProps) {
  const px = useMotionValue(0);
  const py = useMotionValue(0);
  const rx = useSpring(useTransform(py, [-1, 1], [14, -14]), { stiffness: 140, damping: 16 });
  const ry = useSpring(useTransform(px, [-1, 1], [-14, 14]), { stiffness: 140, damping: 16 });
  const tx = useSpring(useTransform(px, [-1, 1], [-8, 8]), { stiffness: 120, damping: 18 });
  const ty = useSpring(useTransform(py, [-1, 1], [-8, 8]), { stiffness: 120, damping: 18 });

  function onMove(e: PointerEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    px.set(((e.clientX - r.left) / r.width) * 2 - 1);
    py.set(((e.clientY - r.top) / r.height) * 2 - 1);
  }
  function onLeave() {
    px.set(0);
    py.set(0);
  }

  return (
    <motion.div
      aria-hidden="true"
      className={cn("orb shrink-0", className)}
      data-state={busy ? "busy" : "idle"}
      style={{ width: size, height: size, ...(interactive ? { rotateX: rx, rotateY: ry, x: tx, y: ty, transformPerspective: 600 } : {}) }}
      onPointerMove={interactive ? onMove : undefined}
      onPointerLeave={interactive ? onLeave : undefined}
    >
      <span className="orb__glow" />
      <span className="orb__core" />
      <span className="orb__swirl" />
    </motion.div>
  );
}
