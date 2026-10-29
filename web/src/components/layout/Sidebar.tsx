import { AnimatePresence, motion } from "motion/react";
import { FileText, MessageSquare, Moon, Plus, Search, Settings, Sun, type LucideIcon } from "lucide-react";
import type { MouseEvent } from "react";
import { Orb } from "@/components/fx/Orb";
import { Kbd } from "@/components/ui/Kbd";
import { Tooltip } from "@/components/ui/Tooltip";
import { ripple, spotlight } from "@/hooks/useEffects";
import { cn } from "@/lib/cn";
import { ariaKeyshortcuts, withHint } from "@/lib/shortcuts";
import { TOOLS } from "@/lib/tools";
import type { Theme } from "@/hooks/useTheme";

export type View = "chat" | "documents";

export interface StatusInfo {
  label: string;
  configured: boolean;
  offline: boolean;
  tip: string;
}

interface SidebarProps {
  view: View;
  docCount: number;
  status: StatusInfo;
  theme: Theme;
  busy: boolean;
  onNewChat: () => void;
  onSearch: () => void;
  onChat: () => void;
  onDocs: () => void;
  onSettings: () => void;
  onToggleTheme: (origin: { x: number; y: number }) => void;
}

function NavItem({ id, icon: Icon, label, active, onClick, badge, title }: { id: string; icon: LucideIcon; label: string; active: boolean; onClick: () => void; badge?: number; title?: string }) {
  return (
    <button
      id={id}
      type="button"
      aria-pressed={active}
      title={title}
      onClick={onClick}
      onPointerDown={ripple}
      className={cn(
        "mp-nav-item group relative flex h-10 w-full items-center gap-3 overflow-hidden rounded-xl px-3 text-sm font-medium transition-colors duration-200",
        active ? "text-fg" : "text-muted hover:text-fg",
      )}
    >
      {active && (
        <motion.span
          layoutId="nav-active"
          className="absolute inset-0 rounded-xl border border-line-strong bg-surface-2 shadow-[inset_0_1px_0_var(--highlight)]"
          transition={{ type: "spring", stiffness: 500, damping: 38 }}
        />
      )}
      <span className="relative z-10 flex items-center gap-3">
        <Icon size={17} aria-hidden="true" className={cn("transition-transform duration-300 group-hover:scale-110", active && "text-primary")} />
        {label}
      </span>
      {!!badge && (
        <motion.span
          key={badge}
          initial={{ scale: 0.6, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className="relative z-10 ml-auto rounded-full bg-primary-soft px-2 py-0.5 text-[11px] font-semibold text-primary"
        >
          {badge}
        </motion.span>
      )}
    </button>
  );
}

export function Sidebar(props: SidebarProps) {
  const { view, docCount, status, theme, busy } = props;

  function themeClick(e: MouseEvent<HTMLButtonElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    props.onToggleTheme({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
  }

  return (
    <div className="flex h-full flex-col gap-1 p-3">
      {/* Brand */}
      <div className="mp-brand flex items-center gap-2.5 px-2 pt-1 pb-4">
        <Orb size={30} busy={busy} />
        <div className="flex flex-col leading-none">
          <span className="text-gradient text-[17px] font-bold tracking-tight">Morphie</span>
          <span className="mt-1 text-[10px] font-semibold tracking-[0.22em] text-subtle">MORPHIE-BOT</span>
        </div>
      </div>

      {/* New chat */}
      <motion.button
        id="newChatBtn"
        type="button"
        onClick={props.onNewChat}
        onPointerDown={ripple}
        title={withHint("Start a new chat", "newChat")}
        aria-keyshortcuts={ariaKeyshortcuts("newChat")}
        whileHover={{ y: -1 }}
        whileTap={{ scale: 0.97 }}
        className="mp-newchat shine relative flex h-11 items-center gap-2.5 overflow-hidden rounded-xl border border-white/10 bg-[linear-gradient(135deg,var(--primary)_0%,var(--indigo)_100%)] px-3.5 text-sm font-semibold text-on-primary shadow-glow transition hover:brightness-110"
      >
        <motion.span className="grid place-items-center" whileHover={{ rotate: 90 }} transition={{ type: "spring", stiffness: 400, damping: 15 }}>
          <Plus size={17} aria-hidden="true" />
        </motion.span>
        New chat
        <Kbd id="newChat" className="ml-auto border-white/20 bg-white/15 text-white/85 shadow-none" />
      </motion.button>

      {/* Search / command menu */}
      <button
        id="cmdBtn"
        type="button"
        aria-haspopup="dialog"
        onClick={props.onSearch}
        title={withHint("Search every page and action", "commandMenu")}
        aria-keyshortcuts={ariaKeyshortcuts("commandMenu")}
        className="mp-nav-item--search group mt-2 flex h-10 items-center gap-3 rounded-xl border border-line bg-surface px-3 text-sm text-muted transition hover:border-line-strong hover:bg-surface-2 hover:text-fg"
      >
        <Search size={16} aria-hidden="true" className="transition-transform duration-300 group-hover:-rotate-12" />
        Search…
        <Kbd id="commandMenu" className="ml-auto" />
      </button>

      <nav className="mp-nav mt-3 flex flex-col gap-1" aria-label="Main">
        <NavItem id="chatBtn" icon={MessageSquare} label="Chat" active={view === "chat"} onClick={props.onChat} />
        <NavItem id="docsBtn" icon={FileText} label="Documents" active={view === "documents"} onClick={props.onDocs} badge={docCount} title={withHint("Upload and manage your documents", "toggleDocs")} />
      </nav>

      {/* What Morphie can reach for */}
      <div className="mt-6 px-2">
        <div className="mb-2 text-[11px] font-semibold tracking-[0.14em] text-subtle uppercase">Tools</div>
        <ul className="grid grid-cols-2 gap-1.5">
          {Object.entries(TOOLS).map(([id, t], i) => (
            <motion.li
              key={id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15 + i * 0.05 }}
              {...spotlight}
              className="spotlight flex items-center gap-2 rounded-xl border border-line bg-surface px-2.5 py-2 text-[12px] text-muted"
            >
              <t.icon size={14} aria-hidden="true" style={{ color: t.hue }} />
              <span className="truncate">{t.name}</span>
            </motion.li>
          ))}
        </ul>
      </div>

      <div className="flex-1" />

      {/* Footer: model badge + theme */}
      <div className="mp-sidebar-foot flex items-center gap-2 border-t border-line pt-3">
        <button
          id="providerBadge"
          type="button"
          onClick={props.onSettings}
          title={status.tip}
          className={cn(
            "mp-provider-badge group flex h-11 min-w-0 flex-1 items-center gap-2.5 rounded-xl border px-3 text-left text-[13px] transition",
            status.configured && !status.offline
              ? "border-line bg-surface hover:border-line-strong hover:bg-surface-2"
              : "is-unconfigured border-warning/40 bg-warning/10 hover:bg-warning/15",
          )}
        >
          <span
            aria-hidden="true"
            className={cn("pulse-dot h-2 w-2 shrink-0 rounded-full", status.offline ? "bg-danger text-danger" : status.configured ? "bg-success text-success" : "bg-warning text-warning")}
          />
          <span id="providerBadgeName" className="min-w-0 flex-1 truncate font-medium text-fg">
            {status.label}
          </span>
          <Settings size={15} aria-hidden="true" className="shrink-0 text-subtle transition-transform duration-500 group-hover:rotate-90 group-hover:text-fg" />
        </button>
        <Tooltip label={theme === "dark" ? "Light theme" : "Dark theme"} side="top">
          <button
            id="themeToggleBtn"
            type="button"
            onClick={themeClick}
            data-theme-now={theme}
            aria-label="Toggle light / dark theme"
            className="relative grid h-11 w-11 place-items-center overflow-hidden rounded-xl border border-line bg-surface text-muted transition hover:border-line-strong hover:bg-surface-2 hover:text-fg"
          >
            <AnimatePresence mode="wait" initial={false}>
              <motion.span
                key={theme}
                initial={{ rotate: -90, scale: 0.4, opacity: 0 }}
                animate={{ rotate: 0, scale: 1, opacity: 1 }}
                exit={{ rotate: 90, scale: 0.4, opacity: 0 }}
                transition={{ type: "spring", stiffness: 420, damping: 22 }}
                className="grid place-items-center"
              >
                {theme === "dark" ? <Moon size={17} aria-hidden="true" /> : <Sun size={17} aria-hidden="true" />}
              </motion.span>
            </AnimatePresence>
          </button>
        </Tooltip>
      </div>
    </div>
  );
}
