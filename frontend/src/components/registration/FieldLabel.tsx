"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface FieldLabelProps {
  label: string;
  required?: boolean;
  icon?: ReactNode;
  className?: string;
}

export default function FieldLabel({
  label,
  required = false,
  icon,
  className,
}: FieldLabelProps) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      {icon ? <span className="flex shrink-0 items-center justify-center">{icon}</span> : null}
      <span className="text-[11px] font-medium uppercase tracking-[0.14em] text-white/55">
        {label}
      </span>
      {required && (
        <span className="rounded-full border border-amber-400/20 bg-amber-500/[0.08] px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-amber-200/90">
          Required
        </span>
      )}
    </span>
  );
}
