import { useEffect, type PointerEvent as ReactPointerEvent } from "react";

const prefersReduced = () =>
  typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Writes the pointer position into --mx / --my on <html>, once per frame (drives the background cursor glow). */
export function useCursorGlow() {
  useEffect(() => {
    if (prefersReduced() || window.matchMedia?.("(pointer: coarse)").matches) return;
    let frame = 0;
    let x = 0;
    let y = 0;
    const onMove = (e: PointerEvent) => {
      x = e.clientX;
      y = e.clientY;
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        document.documentElement.style.setProperty("--mx", `${x}px`);
        document.documentElement.style.setProperty("--my", `${y}px`);
      });
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      cancelAnimationFrame(frame);
    };
  }, []);
}

/** Pointer handlers for `.spotlight` elements: the glow and the bright border follow the cursor. */
export const spotlight = {
  onPointerMove(e: ReactPointerEvent<HTMLElement>) {
    const el = e.currentTarget;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--sx", `${e.clientX - r.left}px`);
    el.style.setProperty("--sy", `${e.clientY - r.top}px`);
    el.style.setProperty("--spot", "1");
  },
  onPointerLeave(e: ReactPointerEvent<HTMLElement>) {
    e.currentTarget.style.setProperty("--spot", "0");
  },
};

/** A material-style ripple from the press point. The element needs `relative overflow-hidden`. */
export function ripple(e: ReactPointerEvent<HTMLElement>) {
  if (prefersReduced()) return;
  const el = e.currentTarget;
  const r = el.getBoundingClientRect();
  const size = Math.max(r.width, r.height) * 2.2;
  const dot = document.createElement("span");
  dot.className = "ripple";
  dot.style.width = dot.style.height = `${size}px`;
  dot.style.left = `${e.clientX - r.left}px`;
  dot.style.top = `${e.clientY - r.top}px`;
  dot.setAttribute("aria-hidden", "true");
  el.appendChild(dot);
  window.setTimeout(() => dot.remove(), 650);
}
