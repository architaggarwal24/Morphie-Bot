// One registry of keyboard shortcuts, shown wherever the action appears (buttons, tooltips, the command menu).
// `mod` = Cmd on Mac, Ctrl elsewhere. Chords with `mod` work inside the message box (they can't type a character);
// plain keys never fire while someone is typing in a field.

export interface ShortcutDef {
  key: string;
  mod?: boolean;
  shift?: boolean;
}

export type ShortcutId = "commandMenu" | "newChat" | "focusInput" | "toggleDocs";

export const SHORTCUTS: Record<ShortcutId, ShortcutDef> = {
  commandMenu: { key: "k", mod: true },
  newChat: { key: "o", mod: true, shift: true },
  focusInput: { key: "/" },
  toggleDocs: { key: "d", mod: true, shift: true },
};

const platform =
  typeof navigator !== "undefined"
    ? ((navigator as any).userAgentData?.platform as string | undefined) || navigator.platform || ""
    : "";
export const IS_MAC = /Mac|iPhone|iPad|iPod/i.test(platform);

export function formatShortcut(def: ShortcutDef, mac = IS_MAC): string {
  const key = def.key.length === 1 ? def.key.toUpperCase() : def.key;
  if (mac) return (def.mod ? "⌘" : "") + (def.shift ? "⇧" : "") + key;
  return (def.mod ? "Ctrl+" : "") + (def.shift ? "Shift+" : "") + key;
}

export function shortcutLabel(id: ShortcutId): string {
  return SHORTCUTS[id] ? formatShortcut(SHORTCUTS[id]) : "";
}

export function ariaKeyshortcuts(id: ShortcutId): string {
  const def = SHORTCUTS[id];
  const key = def.key.length === 1 ? def.key.toUpperCase() : def.key;
  return (def.mod ? (IS_MAC ? "Meta+" : "Control+") : "") + (def.shift ? "Shift+" : "") + key;
}

export function isTypingTarget(node: EventTarget | null): boolean {
  const el = node as Element | null;
  if (!el || typeof el.closest !== "function") return false;
  const field = el.closest("input, textarea, select, [contenteditable]") as HTMLInputElement | null;
  if (!field) return false;
  if (field.tagName === "INPUT") return !/^(checkbox|radio|button|submit|reset|file|range|color|image)$/.test(field.type);
  return true;
}

export function matchesShortcut(e: KeyboardEvent, def: ShortcutDef, mac = IS_MAC): boolean {
  if (!e.key || e.key.toLowerCase() !== def.key) return false;
  const modDown = mac ? e.metaKey : e.ctrlKey;
  const otherMod = mac ? e.ctrlKey : e.metaKey;
  return !!def.mod === modDown && !otherMod && !!def.shift === e.shiftKey && !e.altKey;
}

/** Tooltip text: "Base text (shortcut)". */
export function withHint(base: string, id?: ShortcutId): string {
  const label = id ? shortcutLabel(id) : "";
  return label ? (base ? `${base} (${label})` : label) : base;
}
