import type { LucideIcon } from "lucide-react";

type WorkspaceCounterProps = {
  label: string;
  value: number;
  hint?: string;
  icon: LucideIcon;
};

export function WorkspaceCounter({ label, value, icon: Icon }: WorkspaceCounterProps) {
  return (
    <div className="flex items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border)] bg-white/[0.02] px-2 py-1">
      <Icon className="h-3.5 w-3.5 text-[color:var(--aqt-fg-dim)]" />
      <span className="text-sm font-semibold leading-none text-[color:var(--aqt-fg)]">{value}</span>
      <span className="text-[10px] uppercase tracking-[0.12em] text-[color:var(--aqt-fg-dim)]">{label}</span>
    </div>
  );
}
