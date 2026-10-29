import { useCallback, useEffect, useState } from "react";
import { local, read, write } from "@/lib/storage";

export type Theme = "dark" | "light";
export const THEME_KEY = "morphie-theme";

function current(): Theme {
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

function apply(theme: Theme) {
  const root = document.documentElement;
  root.setAttribute("data-theme", theme);
  root.style.colorScheme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#07060f" : "#f6f4fb");
}

/** Dark unless the person has explicitly chosen light (persisted). */
export function initTheme() {
  apply(read(local(), THEME_KEY) === "light" ? "light" : "dark");
}

const reduced = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(current);

  useEffect(() => {
    const obs = new MutationObserver(() => setTheme(current()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);

  /** Flips the theme with a circular reveal that grows from (x, y) - usually the toggle button. */
  const toggle = useCallback((origin?: { x: number; y: number }) => {
    const next: Theme = current() === "dark" ? "light" : "dark";
    write(local(), THEME_KEY, next);
    const doc = document as Document & { startViewTransition?: (cb: () => void) => { ready: Promise<void> } };
    if (!doc.startViewTransition || reduced()) {
      apply(next);
      return;
    }
    const x = origin?.x ?? window.innerWidth / 2;
    const y = origin?.y ?? window.innerHeight / 2;
    const r = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
    const t = doc.startViewTransition(() => apply(next));
    t.ready
      .then(() => {
        document.documentElement.animate(
          { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${r}px at ${x}px ${y}px)`] },
          { duration: 650, easing: "cubic-bezier(.22,1,.36,1)", pseudoElement: "::view-transition-new(root)" },
        );
      })
      .catch(() => {});
  }, []);

  return { theme, toggle };
}
