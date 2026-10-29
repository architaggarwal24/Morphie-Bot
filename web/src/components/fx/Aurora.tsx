import { useCursorGlow } from "@/hooks/useEffects";

/** The living backdrop: drifting aurora blobs, a fading grid, film grain, and a glow that follows the cursor. */
export function Aurora() {
  useCursorGlow();
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-bg">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,var(--bg-2),transparent_70%)]" />
      <div className="aurora-blob aurora-a" style={{ width: "55vmax", height: "55vmax", left: "-12vmax", top: "-20vmax", background: "radial-gradient(circle, var(--aurora-1), transparent 65%)" }} />
      <div className="aurora-blob aurora-b" style={{ width: "50vmax", height: "50vmax", right: "-14vmax", top: "-8vmax", background: "radial-gradient(circle, var(--aurora-2), transparent 65%)" }} />
      <div className="aurora-blob aurora-c" style={{ width: "42vmax", height: "42vmax", left: "25vw", bottom: "-24vmax", background: "radial-gradient(circle, var(--aurora-3), transparent 65%)" }} />
      <div className="aurora-blob aurora-d" style={{ width: "30vmax", height: "30vmax", right: "8vw", bottom: "-6vmax", background: "radial-gradient(circle, var(--aurora-4), transparent 65%)" }} />
      <div className="bg-grid absolute inset-0" />
      <div className="cursor-glow absolute inset-0" />
      <div className="bg-noise absolute inset-0" />
    </div>
  );
}
