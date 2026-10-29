import { AnimatePresence, motion } from "motion/react";
import { ArrowUp, AtSign, FileText, Paperclip, Slash, Square, X } from "lucide-react";
import { useEffect, useMemo, useState, type ClipboardEvent, type KeyboardEvent, type RefObject } from "react";
import { Magnetic } from "@/components/fx/Magnetic";
import { Kbd } from "@/components/ui/Kbd";
import { Tooltip } from "@/components/ui/Tooltip";
import { ripple } from "@/hooks/useEffects";
import type { Doc } from "@/hooks/useDocuments";
import { cn } from "@/lib/cn";
import { SLASH_COMMANDS, commandForTool, findTrigger, type Trigger } from "@/lib/commands";
import { TOOLS } from "@/lib/tools";

interface ComposerProps {
  inputRef: RefObject<HTMLTextAreaElement | null>;
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void; // send, or stop while busy
  busy: boolean;
  onAttach: () => void;
  docCount: number;
  documents: Doc[];
  tool: string | null;
  onTool: (tool: string | null) => void;
  mentions: Doc[];
  onMentions: (docs: Doc[]) => void;
  onPasteFiles: (files: File[]) => void;
}

const MAX_HEIGHT = 200;

interface Option {
  key: string;
  label: string;
  hint: string;
  icon: typeof FileText;
  hue: string;
  pick: () => void;
}

export function Composer(props: ComposerProps) {
  const { inputRef, value, onChange, onSubmit, busy, onAttach, docCount, documents, tool, onTool, mentions, onMentions, onPasteFiles } = props;
  const [focused, setFocused] = useState(false);
  const [trigger, setTrigger] = useState<Trigger | null>(null);
  const [active, setActive] = useState(0);

  // autosize: grow with the text up to MAX_HEIGHT, then scroll
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, MAX_HEIGHT) + "px";
  }, [value, inputRef]);

  function updateTrigger(text: string) {
    const el = inputRef.current;
    const caret = el ? el.selectionStart ?? text.length : text.length;
    const t = findTrigger(text, caret);
    setTrigger(t);
    setActive(0);
  }

  function replaceTrigger(t: Trigger, insert: string) {
    const next = value.slice(0, t.start) + insert + value.slice(t.end);
    onChange(next);
    setTrigger(null);
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (!el) return;
      const pos = t.start + insert.length;
      el.focus();
      el.setSelectionRange(pos, pos);
    });
  }

  const options = useMemo<Option[]>(() => {
    if (!trigger) return [];
    if (trigger.kind === "slash") {
      return SLASH_COMMANDS.filter((c) => c.command.startsWith(trigger.query) || c.label.toLowerCase().includes(trigger.query)).map((c) => ({
        key: c.command,
        label: `/${c.command}`,
        hint: c.hint,
        icon: TOOLS[c.tool].icon,
        hue: TOOLS[c.tool].hue,
        pick: () => {
          onTool(c.tool);
          replaceTrigger(trigger, "");
        },
      }));
    }
    return documents
      .filter((d) => d.name.toLowerCase().includes(trigger.query) && !mentions.some((m) => m.id === d.id))
      .slice(0, 8)
      .map((d) => ({
        key: d.id,
        label: d.name,
        hint: d.search === "semantic" ? "Semantic + keyword search" : "Keyword search",
        icon: FileText,
        hue: "var(--pink)",
        pick: () => {
          onMentions([...mentions, d]);
          replaceTrigger(trigger, `@${d.name} `);
        },
      }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger, documents, mentions, value]);

  const menuOpen = !!trigger && (options.length > 0 || trigger.kind === "mention");

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (menuOpen && options.length) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((a) => (a + 1) % options.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((a) => (a - 1 + options.length) % options.length);
        return;
      }
      if ((e.key === "Enter" || e.key === "Tab") && !e.nativeEvent.isComposing) {
        e.preventDefault();
        options[active]?.pick();
        return;
      }
    }
    if (menuOpen && e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      setTrigger(null);
      return;
    }
    if (e.key === "Backspace" && !value && (tool || mentions.length)) {
      // an empty box: Backspace takes off the last chip
      if (mentions.length) onMentions(mentions.slice(0, -1));
      else onTool(null);
      return;
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      setTrigger(null);
      onSubmit();
    }
  }

  function onPaste(e: ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(e.clipboardData?.files ?? []);
    if (files.length) {
      e.preventDefault();
      onPasteFiles(files);
    }
  }

  const canSend = busy || value.trim().length > 0;
  const toolCmd = commandForTool(tool);
  const chips = !!toolCmd || mentions.length > 0;

  return (
    <div id="composerWrap" className="relative mx-auto w-full max-w-3xl px-3 pb-3 sm:px-6 sm:pb-5">
      {/* slash-command / @mention suggestions */}
      <AnimatePresence>
        {menuOpen && (
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, transition: { duration: 0.12 } }}
            transition={{ type: "spring", stiffness: 500, damping: 34 }}
            className="glass-strong absolute right-3 bottom-full left-3 z-30 mb-2 overflow-hidden rounded-2xl p-1.5 sm:right-6 sm:left-6"
          >
            <div className="flex items-center gap-2 px-2.5 pt-1.5 pb-1 text-[10.5px] font-semibold tracking-[0.14em] text-subtle uppercase">
              {trigger?.kind === "slash" ? <Slash size={11} aria-hidden="true" /> : <AtSign size={11} aria-hidden="true" />}
              {trigger?.kind === "slash" ? "Use a tool" : "Ask about a document"}
            </div>
            {options.length === 0 ? (
              <div className="px-3 py-2.5 text-[13px] text-muted">{documents.length ? "No document matches that." : "Upload a document first to mention it."}</div>
            ) : (
              <ul role="listbox" id="composerSuggestions" aria-label={trigger?.kind === "slash" ? "Tools" : "Documents"}>
                {options.map((o, i) => (
                  <li
                    key={o.key}
                    id={`composer-opt-${i}`}
                    role="option"
                    aria-selected={i === active}
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseMove={() => setActive(i)}
                    onClick={() => o.pick()}
                    className={cn("relative flex cursor-pointer items-center gap-3 rounded-xl px-2.5 py-2 text-[13.5px]", i === active ? "text-fg" : "text-muted")}
                  >
                    {i === active && <motion.span layoutId="composer-opt" className="absolute inset-0 rounded-xl bg-primary-soft" transition={{ type: "spring", stiffness: 600, damping: 40 }} />}
                    <span
                      className="relative grid h-7 w-7 shrink-0 place-items-center rounded-lg border"
                      style={{ color: o.hue, borderColor: `color-mix(in srgb, ${o.hue} 35%, transparent)`, background: `color-mix(in srgb, ${o.hue} 12%, transparent)` }}
                    >
                      <o.icon size={14} aria-hidden="true" />
                    </span>
                    <span className="relative min-w-0 flex-1 truncate font-medium">{o.label}</span>
                    <span className="relative hidden truncate text-[12px] text-subtle sm:block">{o.hint}</span>
                  </li>
                ))}
              </ul>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      <motion.div
        id="composer"
        layout
        data-beam={busy ? "fast" : focused ? "on" : "off"}
        className={cn("border-beam glass-strong relative flex flex-col rounded-[22px] p-2 transition-shadow duration-300", focused && "shadow-glow")}
      >
        <AnimatePresence initial={false}>
          {chips && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
              <div className="flex flex-wrap gap-1.5 px-1.5 pt-0.5 pb-1.5">
                {toolCmd && (
                  <motion.span layout initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className="tool-chip inline-flex items-center gap-1.5 rounded-full border border-primary/35 bg-primary-soft py-1 pr-1 pl-2.5 text-[12px] font-medium text-fg">
                    {(() => {
                      const Icon = TOOLS[toolCmd.tool].icon;
                      return <Icon size={12} style={{ color: TOOLS[toolCmd.tool].hue }} aria-hidden="true" />;
                    })()}
                    Use {toolCmd.label}
                    <button type="button" aria-label={`Don't force ${toolCmd.label}`} onClick={() => onTool(null)} className="grid h-5 w-5 place-items-center rounded-full text-subtle hover:bg-surface-3 hover:text-fg">
                      <X size={11} aria-hidden="true" />
                    </button>
                  </motion.span>
                )}
                {mentions.map((d) => (
                  <motion.span key={d.id} layout initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className="mention-chip inline-flex max-w-[16rem] items-center gap-1.5 rounded-full border border-pink/35 bg-pink/10 py-1 pr-1 pl-2.5 text-[12px] font-medium text-fg">
                    <FileText size={12} className="shrink-0 text-pink" aria-hidden="true" />
                    <span className="truncate">{d.name}</span>
                    <button type="button" aria-label={`Stop asking about ${d.name}`} onClick={() => onMentions(mentions.filter((m) => m.id !== d.id))} className="grid h-5 w-5 shrink-0 place-items-center rounded-full text-subtle hover:bg-surface-3 hover:text-fg">
                      <X size={11} aria-hidden="true" />
                    </button>
                  </motion.span>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        <div className="flex items-end gap-2">
          <Tooltip label={docCount ? `Documents (${docCount})` : "Upload documents"}>
            <button
              type="button"
              onClick={onAttach}
              onPointerDown={ripple}
              aria-label="Documents"
              className="relative grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-xl text-muted transition hover:bg-surface-2 hover:text-fg"
            >
              <Paperclip size={18} aria-hidden="true" />
              {docCount > 0 && <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-primary shadow-[0_0_8px_var(--primary)]" />}
            </button>
          </Tooltip>
          <label htmlFor="input" className="sr-only">
            Message Morphie
          </label>
          <textarea
            id="input"
            ref={inputRef}
            rows={1}
            value={value}
            role="combobox"
            aria-expanded={menuOpen}
            aria-controls={menuOpen ? "composerSuggestions" : undefined}
            aria-autocomplete="list"
            aria-activedescendant={menuOpen && options.length ? `composer-opt-${active}` : undefined}
            onChange={(e) => {
              onChange(e.target.value);
              updateTrigger(e.target.value);
            }}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            onClick={() => updateTrigger(value)}
            onFocus={() => setFocused(true)}
            onBlur={() => {
              setFocused(false);
              setTrigger(null);
            }}
            placeholder={tool ? "Ask your question…" : "Ask Morphie anything…  ( / for tools, @ for documents )"}
            className="scrollbar-thin max-h-[200px] min-h-10 flex-1 resize-none bg-transparent px-1 py-2.5 text-[15px] leading-6 text-fg placeholder:text-subtle focus:outline-none focus-visible:outline-none"
          />
          <Magnetic strength={0.3}>
            <motion.button
              id="sendBtn"
              type="button"
              onClick={onSubmit}
              onPointerDown={ripple}
              disabled={!canSend}
              aria-label={busy ? "Stop" : "Send"}
              whileTap={{ scale: 0.9 }}
              className={cn(
                "mp-composer-btn relative grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-xl text-on-primary transition-[filter,opacity,box-shadow] duration-200 disabled:opacity-35",
                busy ? "mp-composer-btn--stop bg-surface-3 text-fg ring-1 ring-line-strong" : "bg-[linear-gradient(135deg,var(--primary),var(--indigo))] shadow-glow hover:brightness-110",
              )}
            >
              {busy && (
                <svg aria-hidden="true" className="absolute inset-0 h-full w-full animate-[spin_1.1s_linear_infinite]" viewBox="0 0 40 40">
                  <circle cx="20" cy="20" r="18" fill="none" stroke="url(#stopGrad)" strokeWidth="2" strokeDasharray="30 90" strokeLinecap="round" />
                  <defs>
                    <linearGradient id="stopGrad">
                      <stop offset="0" stopColor="var(--cyan)" />
                      <stop offset="1" stopColor="var(--primary)" />
                    </linearGradient>
                  </defs>
                </svg>
              )}
              <AnimatePresence mode="wait" initial={false}>
                <motion.span
                  key={busy ? "stop" : "send"}
                  initial={{ scale: 0.3, opacity: 0, rotate: busy ? -45 : 45 }}
                  animate={{ scale: 1, opacity: 1, rotate: 0 }}
                  exit={{ scale: 0.3, opacity: 0 }}
                  transition={{ type: "spring", stiffness: 500, damping: 25 }}
                  className="relative grid place-items-center"
                >
                  {busy ? <Square size={13} fill="currentColor" aria-hidden="true" /> : <ArrowUp size={18} strokeWidth={2.4} aria-hidden="true" />}
                </motion.span>
              </AnimatePresence>
            </motion.button>
          </Magnetic>
        </div>
      </motion.div>
      <p className="mp-composer-hint mt-2 hidden items-center justify-center gap-1.5 text-center text-[12px] text-subtle sm:flex">
        <Kbd>/</Kbd> tools <span className="mx-1 opacity-50">·</span> <Kbd>@</Kbd> a document <span className="mx-1 opacity-50">·</span> paste or drop files <span className="mx-1 opacity-50">·</span>
        <Kbd id="focusInput" /> to focus
      </p>
    </div>
  );
}
