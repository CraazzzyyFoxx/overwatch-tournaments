"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { LogStatsName } from "@/types/stats.types";
import { getHumanizedStats } from "@/lib/stats";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SearchField } from "@/components/ui/search-field";

const MIN_AXES = 3;
const MAX_AXES = 8;

interface Props {
  /** Currently plotted axes (order preserved). */
  selected: LogStatsName[];
  /** Every stat the hero has data for (selected + addable). */
  candidates: LogStatsName[];
  /** Add when absent / remove when present (parent enforces the 3–8 bounds). */
  onToggle: (name: LogStatsName) => void;
}

/** Radar axis editor: selected stats are removable chips (✕); a "+ Add" chip
 *  opens a searchable list of the remaining stats to add. Mirrors the mockup —
 *  add/remove any number of axes (kept within 3–8). */
const RadarAxisPicker = ({ selected, candidates, onToggle }: Props) => {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const available = useMemo(() => candidates.filter((c) => !selected.includes(c)), [candidates, selected]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? available.filter((c) => getHumanizedStats(c).toLowerCase().includes(q)) : available;
  }, [available, query]);

  const canRemove = selected.length > MIN_AXES;
  const canAdd = selected.length < MAX_AXES && available.length > 0;

  return (
    <div className="flex flex-wrap items-center justify-center gap-1.5">
      {selected.map((name) => (
        <span key={name} className="aqt-filter-chip active inline-flex items-center">
          {getHumanizedStats(name)}
          {canRemove ? (
            <button
              type="button"
              onClick={() => onToggle(name)}
              className="-mr-0.5 inline-flex items-center justify-center rounded-sm text-(--aqt-fg-muted) hover:text-[color:var(--aqt-fg)]"
              aria-label={t("users.heroes.removeAxis", { stat: getHumanizedStats(name) })}
            >
              <X aria-hidden className="h-3 w-3" />
            </button>
          ) : null}
        </span>
      ))}

      <Popover open={open} onOpenChange={(o) => { setOpen(o); if (!o) setQuery(""); }}>
        <PopoverTrigger asChild>
          <button
            type="button"
            disabled={!canAdd}
            className={cn(
              "aqt-filter-chip inline-flex items-center gap-1",
              !canAdd && "cursor-not-allowed opacity-40"
            )}
            title={canAdd ? t("users.heroes.addAxis") : t("users.heroes.upToAxes", { count: MAX_AXES })}
          >
            <Plus aria-hidden className="h-3 w-3" />
            {t("common.add")}
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="center"
          className="w-56 border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] p-0"
        >
          <div className="border-b border-[color:var(--aqt-border)] p-2">
            <SearchField
              autoFocus
              label={t("users.heroes.searchStats")}
              placeholder={t("users.heroes.searchStats")}
              value={query}
              onValueChange={setQuery}
            />
          </div>
          <div className="max-h-64 overflow-y-auto py-1">
            {filtered.map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => onToggle(name)}
                className="block w-full px-3 py-1.5 text-left text-caption text-[color:var(--aqt-fg)] transition-colors hover:bg-[hsl(0_0%_100%/0.05)]"
              >
                {getHumanizedStats(name)}
              </button>
            ))}
            {filtered.length === 0 ? (
              <div className="px-3 py-3 text-center text-label text-[color:var(--aqt-fg-dim)]">
                {available.length === 0 ? t("users.heroes.allStatsAdded") : t("users.heroes.noMatch")}
              </div>
            ) : null}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
};

export default RadarAxisPicker;
