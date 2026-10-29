import { motion } from "motion/react";
import { FileText, Menu, SquarePen } from "lucide-react";
import { Orb } from "@/components/fx/Orb";
import { Tooltip } from "@/components/ui/Tooltip";
import { ExportMenu } from "./ExportMenu";
import { cn } from "@/lib/cn";

interface HeaderProps {
  onMenu: () => void;
  onDocs: () => void;
  onNewChat: () => void;
  docsOpen: boolean;
  docCount: number;
  busy: boolean;
  canExport: boolean;
  onExportMarkdown: () => void;
  onCopyAll: () => void;
  onPrint: () => void;
}

export function Header({ onMenu, onDocs, onNewChat, docsOpen, docCount, busy, canExport, onExportMarkdown, onCopyAll, onPrint }: HeaderProps) {
  return (
    <header id="chatHeader" className="relative z-20 flex h-14 shrink-0 items-center gap-2 px-3 sm:px-5">
      <button
        id="sidebarToggleBtn"
        type="button"
        aria-label="Menu"
        onClick={onMenu}
        className="mp-header-btn grid h-10 w-10 place-items-center rounded-xl text-muted transition hover:bg-surface-2 hover:text-fg lg:hidden"
      >
        <Menu size={19} aria-hidden="true" />
      </button>
      <div className="flex items-center gap-2 lg:hidden">
        <Orb size={22} busy={busy} />
        <span className="mp-header-title text-gradient text-[15px] font-bold">Morphie</span>
      </div>
      <div className="hidden items-center gap-2 lg:flex">
        <span className="mp-header-sub flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-[12px] text-muted">
          <motion.span
            aria-hidden="true"
            className={cn("h-1.5 w-1.5 rounded-full", busy ? "bg-cyan" : "bg-success")}
            animate={busy ? { scale: [1, 1.6, 1], opacity: [1, 0.5, 1] } : { scale: 1 }}
            transition={busy ? { repeat: Infinity, duration: 1 } : {}}
          />
          {busy ? "Morphie is working…" : "Chat · Documents · Tools"}
        </span>
      </div>
      <span className="mp-header-spacer flex-1" />
      <Tooltip label="New chat" side="bottom">
        <button type="button" aria-label="New chat" onClick={onNewChat} className="grid h-10 w-10 place-items-center rounded-xl text-muted transition hover:bg-surface-2 hover:text-fg lg:hidden">
          <SquarePen size={18} aria-hidden="true" />
        </button>
      </Tooltip>
      <ExportMenu disabled={!canExport} onMarkdown={onExportMarkdown} onCopy={onCopyAll} onPrint={onPrint} />
      <Tooltip label={docsOpen ? "Close documents" : "Documents"} side="bottom">
        <button
          type="button"
          aria-label="Toggle documents"
          aria-pressed={docsOpen}
          onClick={onDocs}
          className={cn(
            "relative grid h-10 w-10 place-items-center rounded-xl border transition",
            docsOpen ? "border-primary/40 bg-primary-soft text-primary" : "border-transparent text-muted hover:bg-surface-2 hover:text-fg",
          )}
        >
          <FileText size={18} aria-hidden="true" />
          {docCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-primary px-1 text-[10px] font-bold text-on-primary">{docCount}</span>
          )}
        </button>
      </Tooltip>
    </header>
  );
}
