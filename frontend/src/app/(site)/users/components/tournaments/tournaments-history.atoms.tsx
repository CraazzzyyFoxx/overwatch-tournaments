import React from "react";
import { cn } from "@/lib/utils";

export const StatLine = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="grid grid-cols-[1fr_auto] gap-1.5 text-[14.5px] text-[color:var(--aqt-fg-muted)]">
    <span>{label}</span>
    <span className="aqt-mono">{children}</span>
  </div>
);

export const HeaderCell = ({ children, className }: { children: React.ReactNode; className?: string }) => (
  <span
    className={cn(
      "text-[12px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]",
      className
    )}
  >
    {children}
  </span>
);
