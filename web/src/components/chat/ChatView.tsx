import { AnimatePresence, motion } from "motion/react";
import { ArrowDown } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type DragEvent } from "react";
import type { Message } from "@/hooks/useChat";
import { MessageRow } from "./MessageRow";
import { WelcomeHero } from "./WelcomeHero";

interface Props {
  messages: Message[];
  busy: boolean;
  needsKey: boolean;
  onPick: (prompt: string) => void;
  onAddKey: () => void;
  onRegenerate: (id: string) => void;
  onEdit: (id: string) => void;
  onFollowup: (text: string) => void;
  onDropFiles?: (files: File[]) => void;
}

const NEAR_BOTTOM = 120;

export function ChatView({ messages, busy, needsKey, onPick, onAddKey, onRegenerate, onEdit, onFollowup, onDropFiles }: Props) {
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);
  const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
  const ref = useRef<HTMLElement>(null);
  const stick = useRef(true);
  const [away, setAway] = useState(false);

  const onScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM;
    stick.current = near;
    setAway(!near);
  }, []);

  // follow the conversation while the reader is at the bottom; leave them alone if they scrolled up
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && stick.current && messages.length) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // a new question always brings the view down
  const count = messages.length;
  useEffect(() => {
    if (!count) return; // the welcome screen starts at the top
    stick.current = true;
    const el = ref.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [count]);

  function toBottom() {
    stick.current = true;
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: "smooth" });
  }

  return (
    <div
      className="relative min-h-0 flex-1"
      onDragEnter={(e) => {
        if (!onDropFiles || !hasFiles(e)) return;
        e.preventDefault();
        depth.current++;
        setDragging(true);
      }}
      onDragOver={(e) => {
        if (onDropFiles && hasFiles(e)) e.preventDefault();
      }}
      onDragLeave={() => {
        depth.current = Math.max(0, depth.current - 1);
        if (!depth.current) setDragging(false);
      }}
      onDrop={(e) => {
        if (!onDropFiles || !hasFiles(e)) return;
        e.preventDefault();
        depth.current = 0;
        setDragging(false);
        const files = Array.from(e.dataTransfer.files);
        if (files.length) onDropFiles(files);
      }}
    >
      <AnimatePresence>
        {dragging && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="pointer-events-none absolute inset-3 z-30 grid place-items-center rounded-3xl border-2 border-dashed border-primary/60 bg-primary-soft backdrop-blur-sm"
          >
            <motion.div initial={{ scale: 0.9 }} animate={{ scale: 1 }} className="text-center">
              <div className="text-[17px] font-semibold text-fg">Drop to add to your documents</div>
              <div className="mt-1 text-[13px] text-muted">PDF, DOCX, TXT, CSV, JSON · several at once is fine</div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
      <main
        id="chat"
        ref={ref}
        onScroll={onScroll}
        aria-live="off"
        className="scrollbar-thin h-full overflow-y-auto [mask-image:linear-gradient(to_bottom,transparent_0,black_24px,black_calc(100%-28px),transparent_100%)]"
      >
        <AnimatePresence mode="wait" initial={false}>
          {messages.length === 0 ? (
            <motion.div key="empty" className="h-full" exit={{ opacity: 0, scale: 0.98, filter: "blur(6px)", transition: { duration: 0.25 } }}>
              <WelcomeHero onPick={onPick} needsKey={needsKey} onAddKey={onAddKey} />
            </motion.div>
          ) : (
            <motion.div key="thread" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mp-thread mx-auto flex w-full max-w-3xl flex-col gap-7 px-4 pt-6 pb-10 sm:px-6">
              {messages.map((m, i) => (
                <div key={m.id} className="contents">
                  {m.restored && i === 0 && (
                    <div className="flex items-center gap-3 text-[11px] font-semibold tracking-[0.14em] text-subtle uppercase" aria-hidden="true">
                      <span className="h-px flex-1 bg-gradient-to-r from-transparent to-line-strong" />
                      Earlier in this conversation
                      <span className="h-px flex-1 bg-gradient-to-l from-transparent to-line-strong" />
                    </div>
                  )}
                  <MessageRow message={m} busy={busy} onRegenerate={onRegenerate} onEdit={onEdit} onFollowup={onFollowup} />
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </main>
      <AnimatePresence>
        {away && messages.length > 0 && (
          <motion.button
            type="button"
            aria-label="Scroll to the latest message"
            onClick={toBottom}
            initial={{ opacity: 0, y: 10, scale: 0.8 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.8 }}
            whileHover={{ scale: 1.08 }}
            whileTap={{ scale: 0.92 }}
            className="glass-strong absolute right-0 bottom-3 left-0 z-10 mx-auto grid h-9 w-9 place-items-center rounded-full text-fg"
          >
            <ArrowDown size={16} aria-hidden="true" />
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}
