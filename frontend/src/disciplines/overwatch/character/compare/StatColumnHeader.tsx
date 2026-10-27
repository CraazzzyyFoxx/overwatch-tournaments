"use client";

import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { TableHead } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { StatColumnDef, StatKey } from "./stat-columns";

interface StatColumnHeaderProps {
  def: StatColumnDef;
  options: StatColumnDef[];
  /** True when this column drives the single shared row order of the table. */
  isActive: boolean;
  sortDir: "asc" | "desc";
  onSort: () => void;
  onSelect: (key: StatKey) => void;
}

/**
 * One `<th>` of the hero leaderboard: a sort button whose visible label is its
 * accessible name (state lives in the `aria-sort` this cell carries), plus an
 * icon-only picker that swaps which stat the column shows. The column that
 * orders the board is the one in the accent; every other column stays neutral.
 */
const StatColumnHeader = ({
  def,
  options,
  isActive,
  sortDir,
  onSort,
  onSelect,
}: StatColumnHeaderProps) => {
  const t = useTranslations();
  const label = t(def.labelKey);
  const SortIcon = !isActive ? ArrowUpDown : sortDir === "asc" ? ArrowUp : ArrowDown;

  return (
    <TableHead
      scope="col"
      aria-sort={isActive ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
      className={cn(
        // The cell carries the hairline: the table is `border-separate`, where row borders draw nothing.
        "border-b border-[color:var(--aqt-border)] py-2.5 font-normal",
        isActive
          ? "bg-[color:var(--aqt-overlay-1)] shadow-[inset_0_-2px_0_var(--aqt-teal)]"
          : "bg-[color:var(--aqt-card)]"
      )}
    >
      <div className="flex items-center justify-center gap-1">
        <Button
          type="button"
          variant="ghost"
          size="label"
          onClick={onSort}
          className={cn(
            "gap-1.5 whitespace-normal rounded-md px-1.5 py-1 hover:bg-[color:var(--aqt-overlay-3)]",
            isActive
              ? "text-[color:var(--aqt-teal)] hover:text-[color:var(--aqt-teal)]"
              : "text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]"
          )}
        >
          <span className="flex flex-col items-center">
            {/* A narrow column splits "Final blows / 10" into two even lines, never leaving "10" alone. */}
            <span className="text-balance">{label}</span>
            {def.ascending ? (
              <span className="font-medium normal-case tracking-normal text-[color:var(--aqt-fg-faint)]">
                {t("users.heroesCompare.table.lowerIsBetter")}
              </span>
            ) : null}
          </span>
          <SortIcon aria-hidden className={isActive ? undefined : "text-[color:var(--aqt-fg-faint)] opacity-60"} />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("users.heroesCompare.table.selectStat", { stat: label })}
              className="text-[color:var(--aqt-fg-faint)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
            >
              <ChevronDown aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="center" className="max-h-[340px] w-52 overflow-y-auto">
            <DropdownMenuRadioGroup value={def.key} onValueChange={onSelect}>
              {options.map((opt) => (
                <DropdownMenuRadioItem key={opt.key} value={opt.key} className="cursor-pointer">
                  {t(opt.labelKey)}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </TableHead>
  );
};

export default StatColumnHeader;
