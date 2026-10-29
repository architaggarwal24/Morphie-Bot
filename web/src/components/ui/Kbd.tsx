import { cn } from "@/lib/cn";
import { shortcutLabel, type ShortcutId } from "@/lib/shortcuts";

export function Kbd({ id, children, className }: { id?: ShortcutId; children?: string; className?: string }) {
  const label = children ?? (id ? shortcutLabel(id) : "");
  if (!label) return null;
  return (
    <kbd
      className={cn(
        "mp-kbd inline-flex h-5 min-w-5 items-center justify-center rounded-md border border-line bg-surface-2 px-1.5 text-[10.5px] font-medium tracking-wide text-muted shadow-[inset_0_-1px_0_var(--line-strong)]",
        className,
      )}
    >
      {label}
    </kbd>
  );
}
