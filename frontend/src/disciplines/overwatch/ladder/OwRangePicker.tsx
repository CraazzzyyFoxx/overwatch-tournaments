"use client";

import { useState } from "react";
import { ChevronDown, Unlink } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@craazzzyyfoxx/admin-kit/ui/popover";
import { cn } from "@/lib/utils";
import type { NativeTier } from "@/types/discipline.types";

import type { SlotProps } from "../../types";

type Props = SlotProps["nativeRankEditor"];

/** Ladder indices where each native division starts, in ladder order (one grid row per division). */
function divisionRows(ladder: readonly NativeTier[]): { name: string; start: number; size: number }[] {
  const rows: { name: string; start: number; size: number }[] = [];
  ladder.forEach((rank, index) => {
    const last = rows[rows.length - 1];
    if (last && last.name === rank.native_division) last.size += 1;
    else rows.push({ name: rank.native_division, start: index, size: 1 });
  });
  return rows;
}

const capitalize = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

/**
 * Which native ranks land in one division of a custom-scale grid — the Overwatch `nativeRankEditor` slot.
 *
 * Click the first rank, then the last (the same one twice for a single rank); hovering previews the run.
 * Ranks already in another division are drawn filled and say whose they are — taking them is allowed,
 * because the reducer keeps the runs in division order by clipping the neighbours. Unlinked ranks are
 * dashed, so a gap in the ladder is visible from any row. The layout follows the ladder's own
 * `native_division` / `native_tier` fields, so it never assumes a rank count.
 */
export default function OwRangePicker({
  ladder,
  value,
  onChange,
  disabled,
  owners,
  label = ""
}: Readonly<Props>) {
  const t = useTranslations("adminSettings.divisions");
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<number | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);
  const rows = divisionRows(ladder);
  const columns = Math.max(1, ...rows.map((row) => row.size));
  const rankName = (index: number) => ladder[index]?.name ?? `Rank ${index + 1}`;
  const rangeLabel = value
    ? value.from === value.to
      ? rankName(value.from)
      : `${rankName(value.from)} – ${rankName(value.to)}`
    : t("ladder.notLinked");

  const edge = hovered ?? anchor;
  const [low, high] =
    anchor !== null && edge !== null
      ? [Math.min(anchor, edge), Math.max(anchor, edge)]
      : value
        ? [value.from, value.to]
        : [null, null];

  const toggle = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setAnchor(null);
      setHovered(null);
    }
  };

  const pick = (index: number) => {
    if (anchor === null) {
      setAnchor(index);
      return;
    }
    onChange({ from: Math.min(anchor, index), to: Math.max(anchor, index) });
    toggle(false);
  };

  return (
    <Popover open={open} onOpenChange={toggle}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={disabled}
          aria-label={t("table.owRanksOf", { name: label, range: rangeLabel })}
          className={cn(
            "w-full min-w-40 justify-between px-2 tabular-nums",
            !value && "text-warning"
          )}
        >
          <span className="truncate">{rangeLabel}</span>
          <ChevronDown aria-hidden className="size-3 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto p-2" aria-label={t("table.owRanksOfName", { name: label })}>
        <div className="flex flex-col gap-1" onMouseLeave={() => setHovered(null)}>
          {rows.map((row) => (
            <div
              key={row.start}
              style={{ gridTemplateColumns: `92px repeat(${columns}, minmax(0, 1fr))` }}
              className="grid items-center gap-1"
            >
              <span className="pr-2 text-xs text-muted-foreground">{capitalize(row.name)}</span>
              {Array.from({ length: row.size }, (_, column) => {
                const index = row.start + column;
                const owner = owners?.[index] ?? null;
                const other = owner !== null && owner !== label ? owner : null;
                const inRange = low !== null && high !== null && index >= low && index <= high;
                const endpoint = index === low || index === high;
                const rankLabel = other ? `${rankName(index)}, now in ${other}` : rankName(index);
                return (
                  <Button
                    key={index}
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-pressed={inRange}
                    aria-label={rankLabel}
                    title={rankLabel}
                    onClick={() => pick(index)}
                    onMouseEnter={() => setHovered(index)}
                    onFocus={() => setHovered(index)}
                    className={cn(
                      "w-auto min-w-9 border tabular-nums",
                      endpoint
                        ? "border-primary bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground"
                        : inRange
                          ? "border-primary/40 bg-primary/15 hover:bg-primary/15"
                          : other
                            ? "border-transparent bg-muted text-muted-foreground hover:border-border hover:bg-muted"
                            : owners && owner === null
                              ? "border-dashed border-warning/60 hover:bg-muted"
                              : "border-transparent hover:border-border hover:bg-muted"
                    )}
                  >
                    {ladder[index].native_tier}
                  </Button>
                );
              })}
            </div>
          ))}
        </div>
        <div className="mt-2 flex items-start justify-between gap-2 border-t border-border pt-2">
          <p className="max-w-56 text-xs text-muted-foreground" aria-live="polite">
            {anchor === null
              ? t("table.owPickerHint")
              : t("table.owPickerFrom", { rank: rankName(anchor) })}
          </p>
          <Button
            variant="ghost"
            size="sm"
            className="shrink-0"
            disabled={!value}
            onClick={() => {
              onChange(null);
              toggle(false);
            }}
          >
            <Unlink aria-hidden className="size-3" />
            {t("mapping.unlink")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
