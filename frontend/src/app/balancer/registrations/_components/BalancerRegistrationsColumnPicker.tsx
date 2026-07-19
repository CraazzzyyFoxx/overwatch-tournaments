"use client";

import { Settings2 } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

import type { BalancerRegistrationColumnDefinition } from "./balancerRegistrationColumns";

const CATEGORY_LABELS: Record<BalancerRegistrationColumnDefinition["category"], string> = {
  core: "Core",
  meta: "Meta",
  admin: "Admin",
};

interface BalancerRegistrationsColumnPickerProps {
  columns: BalancerRegistrationColumnDefinition[];
  visibility: Record<string, boolean>;
  onToggle: (id: string) => void;
  onReset: () => void;
}

export default function BalancerRegistrationsColumnPicker({
  columns,
  visibility,
  onToggle,
  onReset,
}: BalancerRegistrationsColumnPickerProps) {
  const groups = new Map<BalancerRegistrationColumnDefinition["category"], BalancerRegistrationColumnDefinition[]>();

  for (const column of columns) {
    const list = groups.get(column.category) ?? [];
    list.push(column);
    groups.set(column.category, list);
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="flex h-9 items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border-2)] bg-white/[0.03] px-3 text-xs text-[color:var(--aqt-fg-muted)] transition-colors hover:border-[color:var(--aqt-border-2)] hover:text-[color:var(--aqt-fg)]"
        >
          <Settings2 className="size-3.5" />
          Columns
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 p-3">
        <div className="space-y-3">
          {(["core", "meta", "admin"] as const).map((category) => {
            const items = groups.get(category);
            if (!items || items.length === 0) {
              return null;
            }

            return (
              <div key={category}>
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--aqt-fg-dim)]">
                  {CATEGORY_LABELS[category]}
                </p>
                <div className="space-y-1">
                  {items.map((column) => (
                    <label
                      key={column.id}
                      className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs text-[color:var(--aqt-fg-muted)] hover:bg-white/5 hover:text-[color:var(--aqt-fg)]"
                    >
                      <Checkbox
                        checked={visibility[column.id] !== false}
                        onCheckedChange={() => onToggle(column.id)}
                      />
                      {column.label}
                    </label>
                  ))}
                </div>
              </div>
            );
          })}

          <button
            type="button"
            onClick={onReset}
            className="w-full rounded px-2 py-1 text-[11px] text-[color:var(--aqt-fg-dim)] transition-colors hover:bg-white/5 hover:text-[color:var(--aqt-fg-muted)]"
          >
            Reset to defaults
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
