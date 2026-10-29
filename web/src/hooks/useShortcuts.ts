import { useEffect, useRef } from "react";
import { SHORTCUTS, isTypingTarget, matchesShortcut, type ShortcutId } from "@/lib/shortcuts";

/**
 * One global keydown listener for the whole registry. Plain keys never fire while typing in a field; chords with
 * the platform modifier do. While a dialog is open it owns the keyboard (only the command-menu toggle still works).
 */
export function useShortcuts(handlers: Record<ShortcutId, () => void>, dialogOpen: boolean) {
  const ref = useRef({ handlers, dialogOpen });
  ref.current = { handlers, dialogOpen };

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.defaultPrevented || e.isComposing) return;
      const typing = isTypingTarget(e.target);
      for (const id of Object.keys(SHORTCUTS) as ShortcutId[]) {
        const def = SHORTCUTS[id];
        if (!matchesShortcut(e, def)) continue;
        if (typing && !def.mod) return;
        if (id !== "commandMenu" && ref.current.dialogOpen) return; // a dialog owns the keyboard
        e.preventDefault();
        ref.current.handlers[id]();
        return;
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
}

/** Refresh what is on screen when the window regains focus or the network comes back. */
export function useRevalidate(fn: (force: boolean) => void) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const onFocus = () => ref.current(false);
    const onVisible = () => {
      if (document.visibilityState === "visible") ref.current(false);
    };
    const onOnline = () => ref.current(true);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onOnline);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
    };
  }, []);
}
