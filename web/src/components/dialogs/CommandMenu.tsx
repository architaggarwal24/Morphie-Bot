import { AnimatePresence, motion } from "motion/react";
import { CornerDownLeft, Search, type LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Kbd } from "@/components/ui/Kbd";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/lib/cn";
import type { ShortcutId } from "@/lib/shortcuts";

export interface CommandAction {
  id: string;
  label: string;
  keywords?: string;
  icon: LucideIcon;
  group: "Actions" | "Ask Morphie";
  shortcut?: ShortcutId;
  run: () => void;
}

/** Every typed word must appear somewhere in the label or keywords; label-prefix matches sort first. */
export function filterCommands(actions: CommandAction[], query: string): CommandAction[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return actions;
  return actions
    .filter((a) => {
      const hay = `${a.label} ${a.keywords ?? ""}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    })
    .sort((a, b) => Number(b.label.toLowerCase().startsWith(words[0])) - Number(a.label.toLowerCase().startsWith(words[0])));
}

interface Props {
  open: boolean;
  onClose: () => void;
  actions: CommandAction[];
}

export function CommandMenu({ open, onClose, actions }: Props) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setIndex(0);
      requestAnimationFrame(() => input.current?.focus());
    }
  }, [open]);

  const visible = useMemo(() => filterCommands(actions, query), [actions, query]);

  useEffect(() => {
    setIndex(0);
  }, [query]);

  useEffect(() => {
    list.current?.querySelector(`#cmd-opt-${index}`)?.scrollIntoView({ block: "nearest" });
  }, [index]);

  function runCommand(i: number) {
    const action = visible[i];
    if (!action) return;
    onClose(); // first, so an action that moves focus (or opens a dialog) wins it
    requestAnimationFrame(() => action.run());
  }

  function onCommandKeydown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.nativeEvent.isComposing) return;
    const count = visible.length;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (count) setIndex((index + 1) % count);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (count) setIndex((index - 1 + count) % count);
    } else if (e.key === "Enter") {
      e.preventDefault();
      runCommand(index);
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation(); // not also the panel behind it
      onClose();
    } else if (e.key === "Tab") {
      e.preventDefault(); // the field is the only stop; arrows move through the list
    }
  }

  let lastGroup = "";

  return (
    <Modal open={open} onClose={onClose} id="commandMenu" label="Command menu" placement="top" className="mp-cmd mp-cmd__card max-w-xl overflow-hidden">
      <div className="flex items-center gap-3 border-b border-line px-4">
        <Search size={18} className="shrink-0 text-subtle" aria-hidden="true" />
        <input
          id="cmdInput"
          ref={input}
          autoFocus
          className="mp-cmd__input h-14 flex-1 bg-transparent text-[15px] text-fg placeholder:text-subtle focus:outline-none focus-visible:outline-none"
          type="text"
          role="combobox"
          aria-expanded="true"
          aria-controls="cmdList"
          aria-autocomplete="list"
          aria-label="Search pages and actions"
          aria-activedescendant={visible.length ? `cmd-opt-${index}` : undefined}
          placeholder="Search pages and actions…"
          autoComplete="off"
          spellCheck={false}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onCommandKeydown}
        />
        <Kbd>Esc</Kbd>
      </div>
      <ul id="cmdList" ref={list} role="listbox" aria-label="Pages and actions" className="mp-cmd__list scrollbar-thin max-h-[52vh] overflow-y-auto p-2">
        {visible.map((a, i) => {
          const header = a.group !== lastGroup ? a.group : null;
          lastGroup = a.group;
          const active = i === index;
          return (
            <li key={a.id} role="presentation">
              {header && <div className="px-3 pt-2.5 pb-1.5 text-[10.5px] font-semibold tracking-[0.14em] text-subtle uppercase">{header}</div>}
              <div
                id={`cmd-opt-${i}`}
                role="option"
                aria-selected={active}
                className={cn("mp-cmd__item relative flex h-11 cursor-pointer items-center gap-3 rounded-xl px-3 text-[14px] transition-colors", active ? "text-fg" : "text-muted")}
                onMouseDown={(e) => e.preventDefault()} // keep focus in the field
                onMouseMove={() => index !== i && setIndex(i)}
                onClick={() => runCommand(i)}
              >
                {active && (
                  <motion.span
                    layoutId="cmd-active"
                    className="absolute inset-0 rounded-xl border border-primary/30 bg-primary-soft"
                    transition={{ type: "spring", stiffness: 600, damping: 40 }}
                  />
                )}
                <span className={cn("relative grid h-7 w-7 place-items-center rounded-lg border transition-colors", active ? "border-primary/40 bg-primary/20 text-primary" : "border-line bg-surface")}>
                  <a.icon size={15} aria-hidden="true" />
                </span>
                <span className="mp-cmd__label relative flex-1 truncate">{a.label}</span>
                {a.shortcut && <Kbd id={a.shortcut} className="relative" />}
                <AnimatePresence>
                  {active && (
                    <motion.span initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} className="relative text-subtle">
                      <CornerDownLeft size={14} aria-hidden="true" />
                    </motion.span>
                  )}
                </AnimatePresence>
              </div>
            </li>
          );
        })}
      </ul>
      <div id="cmdEmpty" className="mp-cmd__empty px-4 pb-6 text-center text-[13.5px] text-muted" role="status" hidden={visible.length > 0}>
        Nothing matches that.
      </div>
      <div className="flex items-center gap-4 border-t border-line px-4 py-2.5 text-[11.5px] text-subtle">
        <span className="flex items-center gap-1.5">
          <Kbd>↑</Kbd>
          <Kbd>↓</Kbd> to move
        </span>
        <span className="flex items-center gap-1.5">
          <Kbd>↵</Kbd> to run
        </span>
        <span className="ml-auto flex items-center gap-1.5">
          <Kbd id="commandMenu" /> to toggle
        </span>
      </div>
    </Modal>
  );
}
