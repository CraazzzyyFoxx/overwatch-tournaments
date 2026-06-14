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
  onSelect: (key: StatKey) => void;
  onToggleSort: () => void;
}

const SelectableStatColumn = ({
  def,
  sortDir,
  options,
  data,
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

  const maxValue = useMemo(
    () => sorted.reduce((m, r) => Math.max(m, def.getValue(r)), 0) || 1,
    [sorted, def]
  );

  return (
    <div className="min-w-[270px] flex-1">
      <div className="flex flex-col items-center gap-1.5 border-b border-border/50 px-4 pb-3 pt-3">
        <div className={`h-[3px] w-8 rounded-full opacity-80 ${def.accentColor}`} />
        <div className="flex items-center gap-1">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="flex cursor-pointer items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground transition-colors hover:bg-muted/30 hover:text-foreground"
              >
                {def.shortLabel}
                <ChevronDown className="h-3 w-3 opacity-60" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="center" className="w-52">
              {options.map((opt) => (
                <DropdownMenuItem
                  key={opt.key}
                  onSelect={() => onSelect(opt.key)}
                  className={`cursor-pointer gap-2 ${opt.key === def.key ? "bg-muted/50 font-semibold" : ""}`}
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
            className="rounded p-0.5 text-muted-foreground/60 transition-colors hover:bg-muted/30 hover:text-foreground"
            title={sortDir === "asc" ? "Sort descending" : "Sort ascending"}
          >
            {sortDir === "asc" ? (
              <ArrowUp className="h-3 w-3" />
            ) : (
              <ArrowDown className="h-3 w-3" />
            )}
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
            maxValue={maxValue}
            barColor={def.barColor}
            formatValue={def.formatValue}
            isEven={i % 2 === 0}
          />
        ))}
      </div>
    </div>
  );
};

export default SelectableStatColumn;
