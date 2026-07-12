"use client";

import React from "react";
import { cn } from "@/lib/utils";

import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";

export const AqtSelect = ({
  value,
  onChange,
  options,
  title,
  width = "w-[150px]"
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  title?: string;
  width?: string;
}) => (
  <Select value={value} onValueChange={onChange}>
    <SelectTrigger
      title={title}
      className={cn(
        "aqt-mono h-8 shadow-none border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-[13px] text-[color:var(--aqt-fg-muted)] hover:border-[color:var(--aqt-border-2)] hover:bg-[hsl(0_0%_100%/0.04)] focus:ring-1 focus:ring-[color:var(--aqt-teal)] focus:ring-offset-0",
        width
      )}
    >
      <SelectValue />
    </SelectTrigger>
    <SelectContent className="max-h-[min(var(--radix-select-content-available-height),20rem)]">
      {options.map((o) => (
        <SelectItem key={o.value} value={o.value}>
          {o.label}
        </SelectItem>
      ))}
    </SelectContent>
  </Select>
);

export const PageBtn = ({
  active,
  disabled,
  onClick,
  children
}: {
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}) => (
  <button
    onClick={onClick}
    disabled={disabled}
    className={cn(
      "aqt-mono inline-flex h-8 min-w-[32px] items-center justify-center rounded-[6px] border px-2 text-[13px] transition-colors",
      active
        ? "border-[color:color-mix(in_srgb,var(--aqt-teal)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)] text-[color:var(--aqt-teal)]"
        : "border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]",
      disabled && "cursor-not-allowed opacity-40"
    )}
  >
    {children}
  </button>
);

export const KPI = ({ label, value, unit, color, sub }: { label: string; value: string; unit?: string; color?: string; sub?: string }) => (
  <CardSurface>
    <div className="flex flex-col gap-1">
      <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">{label}</div>
      <div className="aqt-display text-[38px] font-bold leading-[1.1]" style={{ color: color ?? "var(--aqt-fg)" }}>
        {value}
        {unit ? <span className="text-[22px] text-[color:var(--aqt-fg-faint)]">{unit}</span> : null}
      </div>
      {sub ? <div className="aqt-mono text-[12px] text-[color:var(--aqt-fg-dim)]">{sub}</div> : null}
    </div>
  </CardSurface>
);
