"use client";

import { Settings2 } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

import type { ColumnDefinition } from "./participantsColumns";

const CATEGORY_LABELS: Record<string, string> = {
  meta: "General",
  built_in: "Fields",
  custom: "Custom Fields",
};

interface ColumnPickerProps {
  columns: ColumnDefinition[];
  visibility: Record<string, boolean>;
  onToggle: (id: string) => void;
  onReset: () => void;
}

export default function ColumnPicker({
  columns,
  visibility,
  onToggle,
  onReset,
}: ColumnPickerProps) {
  // Group columns by category
  const groups = new Map<string, ColumnDefinition[]>();
  for (const col of columns) {
    const list = groups.get(col.category) ?? [];
    list.push(col);
    groups.set(col.category, list);
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="flex h-9 items-center gap-1.5 rounded-lg border border-white/10 bg-white/3 px-3 text-xs text-white/50 transition-colors hover:border-white/20 hover:text-white/70"
        >
          <Settings2 className="size-3.5" />
          Columns
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 p-3">
        <div className="space-y-3">
          {(["meta", "built_in", "custom"] as const).map((category) => {
            const cols = groups.get(category);
            if (!cols || cols.length === 0) return null;

            return (
              <div key={category}>
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-white/30">
                  {CATEGORY_LABELS[category]}
                </p>
                <div className="space-y-1">
                  {cols.map((col) => (
                    <label
                      key={col.id}
                      className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs text-white/60 hover:bg-white/5 hover:text-white/80"
                    >
                      <Checkbox
                        checked={visibility[col.id] !== false}
                        onCheckedChange={() => onToggle(col.id)}
                      />
                      {col.label}
                    </label>
                  ))}
                </div>
              </div>
            );
          })}

          <button
            type="button"
            onClick={onReset}
            className="w-full rounded px-2 py-1 text-[11px] text-white/40 transition-colors hover:bg-white/5 hover:text-white/60"
          >
            Reset to defaults
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
