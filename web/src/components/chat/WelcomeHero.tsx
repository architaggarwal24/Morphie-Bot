import { motion } from "motion/react";
import { ArrowRight, KeyRound } from "lucide-react";
import { BlurText } from "@/components/fx/BlurText";
import { Orb } from "@/components/fx/Orb";
import { spotlight } from "@/hooks/useEffects";
import { SUGGESTIONS, TOOLS } from "@/lib/tools";

interface Props {
  onPick: (prompt: string) => void;
  needsKey: boolean;
  onAddKey: () => void;
}

export function WelcomeHero({ onPick, needsKey, onAddKey }: Props) {
  return (
    <div className="mp-empty-chat mx-auto flex min-h-full w-full max-w-3xl flex-col items-center [justify-content:safe_center] px-4 py-8 sm:py-10 text-center sm:px-6">
      <motion.div initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: "spring", stiffness: 120, damping: 14 }} className="-my-3 mb-4 scale-[0.72] sm:my-0 sm:mb-7 sm:scale-100">
        <Orb size={104} interactive className="cursor-grab" />
      </motion.div>

      {needsKey ? (
        <motion.button
          type="button"
          onClick={onAddKey}
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          className="mb-5 inline-flex items-center gap-2 rounded-full border border-warning/40 bg-warning/10 px-3.5 py-1.5 text-[12.5px] font-medium text-fg"
        >
          <KeyRound size={13} className="text-warning" aria-hidden="true" /> Add your API key to start
          <ArrowRight size={13} aria-hidden="true" />
        </motion.button>
      ) : (
        <motion.span
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-5 inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3.5 py-1.5 text-[12.5px] font-medium text-muted backdrop-blur"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-cyan shadow-[0_0_8px_var(--cyan)]" /> Chat · Agent tools · Document Q&amp;A
        </motion.span>
      )}

      <h2 className="text-[34px] leading-[1.1] font-bold tracking-[-0.03em] sm:text-5xl">
        <BlurText text="Ask Morphie anything" wordClassName="text-gradient pb-1" />
      </h2>
      <motion.p
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.45, duration: 0.6 }}
        className="mt-4 max-w-md text-[15px] leading-relaxed text-muted"
      >
        It picks the right tool itself: a calculator, the clock, web search, or your uploaded documents. No need to choose.
      </motion.p>

      <div className="mp-suggestions mt-9 grid w-full grid-cols-1 gap-3 sm:grid-cols-2">
        {SUGGESTIONS.map((s, i) => {
          const tool = TOOLS[s.tool];
          return (
            <motion.button
              key={s.prompt}
              type="button"
              onClick={() => onPick(s.prompt)}
              {...spotlight}
              initial={{ opacity: 0, y: 18, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ delay: 0.55 + i * 0.07, type: "spring", stiffness: 260, damping: 24 }}
              whileHover={{ y: -3 }}
              whileTap={{ scale: 0.98 }}
              className="mp-suggestion spotlight glass group flex items-start gap-3.5 rounded-2xl p-4 text-left"
            >
              <span
                className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-6"
                style={{ color: tool.hue, borderColor: `color-mix(in srgb, ${tool.hue} 35%, transparent)`, background: `color-mix(in srgb, ${tool.hue} 14%, transparent)` }}
              >
                <tool.icon size={18} aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[14px] font-semibold text-fg">{s.title}</span>
                <span className="mt-0.5 block text-[13px] leading-snug text-muted">{s.prompt}</span>
              </span>
              <ArrowRight size={16} aria-hidden="true" className="mt-1 shrink-0 -translate-x-1 text-subtle opacity-0 transition-all duration-300 group-hover:translate-x-0 group-hover:text-primary group-hover:opacity-100" />
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}
