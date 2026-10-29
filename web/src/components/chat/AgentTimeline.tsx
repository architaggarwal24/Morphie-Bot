import { AnimatePresence, motion } from "motion/react";
import { Brain, ChevronDown, ExternalLink, Globe, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { Step } from "@/hooks/useChat";
import { cn } from "@/lib/cn";
import { toolMeta } from "@/lib/tools";

function Check() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <motion.path
        d="M3.5 8.5l3 3 6-7"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.4, ease: "easeOut" }}
      />
    </svg>
  );
}

function Spinner() {
  return <span aria-hidden="true" className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent opacity-80" />;
}

function formatMs(ms?: number) {
  if (ms == null) return "";
  if (ms < 1) return "<1 ms";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function hostOf(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function StepRow({ step, index }: { step: Step; index: number }) {
  const [open, setOpen] = useState(false);
  const meta = toolMeta(step.tool);
  const Icon = meta.icon;
  const label = step.state === "error" ? `${meta.name} failed` : step.state === "done" ? meta.done : meta.active;
  const hasDetail = !!(step.input || step.output || step.links?.length);
  return (
    <motion.li
      layout
      initial={{ opacity: 0, x: -10, filter: "blur(4px)" }}
      animate={{ opacity: 1, x: 0, filter: "blur(0px)" }}
      transition={{ type: "spring", stiffness: 380, damping: 30, delay: index * 0.03 }}
      className="mp-step relative py-1"
      data-state={step.state}
      data-tool={step.tool}
    >
      <button
        type="button"
        disabled={!hasDetail}
        aria-expanded={hasDetail ? open : undefined}
        onClick={() => setOpen((o) => !o)}
        className={cn("group/step flex w-full items-center gap-3 rounded-xl py-0.5 pr-2 text-left disabled:cursor-default", hasDetail && "hover:bg-surface")}
      >
        <span
          className="relative z-10 grid h-7 w-7 shrink-0 place-items-center rounded-lg border"
          style={{
            color: meta.hue,
            borderColor: `color-mix(in srgb, ${meta.hue} 35%, transparent)`,
            background: `color-mix(in srgb, ${meta.hue} 14%, transparent)`,
            boxShadow: step.state === "active" ? `0 0 18px color-mix(in srgb, ${meta.hue} 55%, transparent)` : undefined,
          }}
        >
          <Icon size={14} aria-hidden="true" />
        </span>
        <span className="min-w-0">
          <span className={cn("block text-[13px] font-medium", step.state === "active" ? "text-shimmer" : step.state === "error" ? "text-danger" : "text-muted")}>{label}</span>
          {step.input && <span className="block max-w-[34ch] truncate font-mono text-[11.5px] text-subtle sm:max-w-[48ch]">{step.input}</span>}
        </span>
        <span className={cn("ml-1 grid h-5 w-5 shrink-0 place-items-center", step.state === "done" ? "text-success" : step.state === "error" ? "text-danger" : "text-subtle")}>
          {step.state === "active" ? <Spinner /> : step.state === "done" ? <Check /> : <X size={14} aria-hidden="true" />}
        </span>
        {step.ms != null && <span className="text-[11px] text-subtle tabular-nums">{formatMs(step.ms)}</span>}
        {hasDetail && (
          <motion.span animate={{ rotate: open ? 180 : 0 }} className="ml-auto text-subtle opacity-0 transition-opacity group-hover/step:opacity-100" aria-hidden="true">
            <ChevronDown size={13} />
          </motion.span>
        )}
      </button>
      <AnimatePresence initial={false}>
        {open && hasDetail && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 380, damping: 34 }}
            className="overflow-hidden pl-10"
          >
            <div className="mt-1 mb-1.5 space-y-2 rounded-xl border border-line bg-surface p-2.5 text-[12px]">
              {step.input && (
                <div>
                  <div className="mb-0.5 text-[10.5px] font-semibold tracking-[0.12em] text-subtle uppercase">Input</div>
                  <code className="block font-mono break-words whitespace-pre-wrap text-fg">{step.input}</code>
                </div>
              )}
              {step.links?.length ? (
                <div>
                  <div className="mb-1 text-[10.5px] font-semibold tracking-[0.12em] text-subtle uppercase">Results</div>
                  <div className="grid gap-1.5">
                    {step.links.map((l) => (
                      <a
                        key={l.url}
                        href={l.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="group/link flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 transition hover:border-indigo/50 hover:bg-indigo/10"
                      >
                        <Globe size={13} className="shrink-0 text-indigo" aria-hidden="true" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-medium text-fg">{l.title}</span>
                          <span className="block truncate text-[11px] text-subtle">{hostOf(l.url)}</span>
                        </span>
                        <ExternalLink size={12} className="shrink-0 text-subtle transition group-hover/link:text-fg" aria-hidden="true" />
                      </a>
                    ))}
                  </div>
                </div>
              ) : step.output ? (
                <div>
                  <div className="mb-0.5 text-[10.5px] font-semibold tracking-[0.12em] text-subtle uppercase">{step.state === "error" ? "Error" : "Output"}</div>
                  <p className="break-words whitespace-pre-wrap text-muted">{step.output}</p>
                </div>
              ) : null}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  );
}

interface Props {
  steps: Step[];
  thinking: boolean;
  live: boolean; // the turn is still streaming
}

/** What the agent is doing, as an animated timeline. Collapses to a summary once the answer is in. */
export function AgentTimeline({ steps, thinking, live }: Props) {
  const [open, setOpen] = useState(live);
  useEffect(() => {
    if (live) setOpen(true);
    else {
      const t = window.setTimeout(() => setOpen(false), 900);
      return () => window.clearTimeout(t);
    }
  }, [live]);

  const showThinking = live && thinking;
  if (!steps.length && !showThinking) return null;

  const failed = steps.filter((s) => s.state === "error").length;
  const summary = steps.length ? `Used ${steps.length} tool${steps.length > 1 ? "s" : ""}${failed ? ` · ${failed} failed` : ""}` : "Thinking";

  return (
    <div className="mp-steps mb-2" aria-live="polite">
      {!live && steps.length > 0 && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="group flex items-center gap-2 rounded-full border border-line bg-surface px-2.5 py-1 text-[12px] font-medium text-muted transition hover:border-line-strong hover:text-fg"
        >
          <span className="flex -space-x-1.5">
            {steps.slice(0, 4).map((s) => {
              const m = toolMeta(s.tool);
              return (
                <span key={s.id} className="grid h-5 w-5 place-items-center rounded-full border border-bg bg-surface-3" style={{ color: m.hue }}>
                  <m.icon size={11} aria-hidden="true" />
                </span>
              );
            })}
          </span>
          {summary}
          <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ type: "spring", stiffness: 400, damping: 25 }}>
            <ChevronDown size={14} aria-hidden="true" />
          </motion.span>
        </button>
      )}
      <AnimatePresence initial={false}>
        {(open || live) && (
          <motion.div
            key="list"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 32 }}
            className="overflow-hidden"
          >
            <ol className="relative mt-1.5 max-w-xl pl-0.5">
              {/* the connecting rail */}
              {steps.length + (showThinking ? 1 : 0) > 1 && (
                <span aria-hidden="true" className="absolute top-5 bottom-5 left-[14.5px] w-px bg-gradient-to-b from-primary/50 via-line-strong to-transparent" />
              )}
              {steps.map((s, i) => (
                <StepRow key={s.id} step={s} index={i} />
              ))}
              <AnimatePresence>
                {showThinking && (
                  <motion.li
                    key="thinking"
                    layout
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, height: 0 }}
                    className="mp-step flex items-center gap-3 py-1.5"
                    data-state="active"
                  >
                    <span className="relative z-10 grid h-7 w-7 place-items-center rounded-lg border border-primary/35 bg-primary-soft text-primary shadow-[0_0_18px_rgb(139_92_246/0.45)]">
                      <Brain size={14} aria-hidden="true" />
                    </span>
                    <span className="text-shimmer text-[13px] font-medium">Thinking</span>
                    <span className="flex gap-1" aria-hidden="true">
                      {[0, 1, 2].map((i) => (
                        <motion.span
                          key={i}
                          className="h-1 w-1 rounded-full bg-primary"
                          animate={{ opacity: [0.2, 1, 0.2], y: [0, -2, 0] }}
                          transition={{ repeat: Infinity, duration: 1, delay: i * 0.15 }}
                        />
                      ))}
                    </span>
                  </motion.li>
                )}
              </AnimatePresence>
            </ol>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
