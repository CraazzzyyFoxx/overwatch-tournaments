"use client";

import { useMemo } from "react";
import { ChevronDown, ArrowUp, ArrowDown } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { HeroLeaderboardEntry } from "@/types/hero.types";

import { StatColumnDef, StatKey } from "../config/stat-columns";
import BarRow from "./BarRow";

interface SelectableStatColumnProps {
  def: StatColumnDef;
  sortDir: "asc" | "desc";
  options: StatColumnDef[];
  data: HeroLeaderboardEntry[];
  hoveredUserId: number | null;
  onHoverUser: (userId: number | null) => void;
  onSelect: (key: StatKey) => void;
  onToggleSort: () => void;
}

const SelectableStatColumn = ({
  def,
  sortDir,
  options,
  data,
  hoveredUserId,
  onHoverUser,
  onSelect,
  onToggleSort,
}: SelectableStatColumnProps) => {
  const sorted = useMemo(
    () =>
      [...data].sort((a, b) => {
        const va = def.getValue(a);
        const vb = def.getValue(b);
        return sortDir === "asc" ? va - vb : vb - va;
      }),
    [data, def, sortDir]
  );

  const { minValue, maxValue } = useMemo(() => {
    if (sorted.length === 0) return { minValue: 0, maxValue: 1 };
    let min = Infinity;
    let max = -Infinity;
    for (const r of sorted) {
      const v = def.getValue(r);
      if (v < min) min = v;
      if (v > max) max = v;
    }
    return { minValue: min, maxValue: max || 1 };
  }, [sorted, def]);

  return (
    <div className="min-w-[286px] flex-1">
      <div className="flex flex-col items-center gap-2 border-b border-[var(--aqt-border)] bg-white/[0.008] px-3.5 pb-3 pt-3.5">
        <div className={`h-[3px] w-[34px] rounded-full ${def.accentColor}`} />
        <div className="flex items-center gap-1">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-1 text-[11.5px] font-bold uppercase tracking-[0.12em] text-[var(--aqt-fg)] transition-colors hover:bg-white/[0.05]"
              >
                {def.shortLabel}
                <ChevronDown className="h-3 w-3 text-[var(--aqt-fg-faint)]" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="center" className="max-h-[340px] w-52 overflow-y-auto">
              {options.map((opt) => (
                <DropdownMenuItem
                  key={opt.key}
                  onSelect={() => onSelect(opt.key)}
                  className={`cursor-pointer gap-2 ${opt.key === def.key ? "bg-white/[0.06] font-semibold" : ""}`}
                >
                  <span className={`h-2 w-2 shrink-0 rounded-full ${opt.accentColor}`} />
                  {opt.shortLabel}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
          <button
            type="button"
            onClick={onToggleSort}
            className="inline-flex h-[26px] w-[26px] items-center justify-center rounded-md border border-transparent text-[var(--aqt-fg-faint)] transition-colors hover:border-[var(--aqt-border-2)] hover:bg-white/[0.05] hover:text-[var(--aqt-fg)]"
            title={sortDir === "asc" ? "Sort descending" : "Sort ascending"}
          >
            {sortDir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
          </button>
        </div>
      </div>
      <div>
        {sorted.map((entry, i) => (
          <BarRow
            key={entry.user_id}
            entry={entry}
            rank={i + 1}
            value={def.getValue(entry)}
            minValue={minValue}
            maxValue={maxValue}
            barColor={def.barColor}
            formatValue={def.formatValue}
            isHighlighted={entry.user_id === hoveredUserId}
            onHoverUser={onHoverUser}
          />
        ))}
      </div>
    </div>
  );
};

export default SelectableStatColumn;
