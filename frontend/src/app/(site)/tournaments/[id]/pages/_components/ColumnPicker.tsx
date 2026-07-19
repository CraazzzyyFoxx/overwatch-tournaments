"use client";

import { Settings2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Checkbox } from "@/components/ui/checkbox";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

import type { ColumnDefinition } from "./participantsColumns";
import { isMandatoryParticipantColumnId } from "./participants-url-state";

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
  const t = useTranslations();

  const categoryLabel = (category: "meta" | "built_in" | "custom"): string => {
    switch (category) {
      case "meta":
        return t("tournamentDetail.columnCategory.general");
      case "built_in":
        return t("tournamentDetail.columnCategory.fields");
      case "custom":
        return t("tournamentDetail.columnCategory.customFields");
    }
  };

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
          className="flex h-9 items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border-2)] bg-white/3 px-3 text-xs text-[color:var(--aqt-fg-muted)] transition-colors hover:border-[color:var(--aqt-border-2)] hover:text-[color:var(--aqt-fg-muted)]"
        >
          <Settings2 className="size-3.5" />
          {t("common.columns")}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 p-3">
        <div className="space-y-3">
          {(["meta", "built_in", "custom"] as const).map((category) => {
            const cols = groups.get(category);
            if (!cols || cols.length === 0) return null;

            return (
              <div key={category}>
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--aqt-fg-dim)]">
                  {categoryLabel(category)}
                </p>
                <div className="space-y-1">
                  {cols.map((col) => {
                    const mandatory = isMandatoryParticipantColumnId(col.id);
                    return (
                      <label
                        key={col.id}
                        className={
                          mandatory
                            ? "flex cursor-not-allowed items-center gap-2 rounded px-1 py-0.5 text-xs text-[color:var(--aqt-fg-dim)]"
                            : "flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs text-[color:var(--aqt-fg-muted)] hover:bg-white/5 hover:text-[color:var(--aqt-fg)]"
                        }
                      >
                        <Checkbox
                          checked={mandatory || visibility[col.id] !== false}
                          disabled={mandatory}
                          onCheckedChange={() => {
                            if (!mandatory) onToggle(col.id);
                          }}
                        />
                        {col.label}
                      </label>
                    );
                  })}
                </div>
              </div>
            );
          })}

          <button
            type="button"
            onClick={onReset}
            className="w-full rounded px-2 py-1 text-[11px] text-[color:var(--aqt-fg-dim)] transition-colors hover:bg-white/5 hover:text-[color:var(--aqt-fg-muted)]"
          >
            {t("tournamentDetail.resetColumns")}
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
