import type { LucideIcon } from "lucide-react";

type WorkspaceCounterProps = {
  label: string;
  value: number;
  hint?: string;
  icon: LucideIcon;
};

export function WorkspaceCounter({ label, value, icon: Icon }: WorkspaceCounterProps) {
  return (
    <div className="flex items-center gap-1.5 rounded-lg border border-white/8 bg-white/[0.02] px-2 py-1">
      <Icon className="h-3.5 w-3.5 text-white/40" />
      <span className="text-sm font-semibold leading-none text-white/88">{value}</span>
      <span className="text-[10px] uppercase tracking-[0.12em] text-white/30">{label}</span>
    </div>
  );
}
