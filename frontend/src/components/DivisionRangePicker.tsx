"use client";

import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { triggerChevronClass } from "@/components/ui/chevron";
import Image from "@/components/ui/image";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { type DivisionGridLike, sortTiersDescending } from "@/lib/divisions/grid";
import { cn } from "@/lib/utils";
import type { DivisionTier } from "@/types/workspace.types";

/** "Gold 3" → row "Gold", cell "3"; "Diamond IV" → "Diamond", "IV". A name without a trailing step is a row of its own. */
const STEP = /^(.+?)\s+(\d+|[IVX]+)$/;

interface TierRow {
  name: string;
  cells: { tier: DivisionTier; step: string | null }[];
}

/** The grid best first; consecutive tiers sharing a name before their step fold into one row. */
function tierRows(grid: DivisionGridLike): TierRow[] {
  const rows: TierRow[] = [];
  for (const tier of sortTiersDescending(grid)) {
    const match = STEP.exec(tier.name.trim());
    const last = rows.at(-1);
    if (match && last?.name === match[1] && last.cells[0].step !== null) {
      last.cells.push({ tier, step: match[2] });
    } else {
      rows.push({ name: match ? match[1] : tier.name, cells: [{ tier, step: match ? match[2] : null }] });
    }
  }
  return rows;
}

const ARROWS: Record<string, [row: number, col: number]> = {
  ArrowUp: [-1, 0],
  ArrowDown: [1, 0],
  ArrowLeft: [0, -1],
  ArrowRight: [0, 1]
};
const clamp = (value: number, max: number) => Math.min(Math.max(value, 0), max);

interface DivisionRangePickerProps {
  grid: DivisionGridLike;
  /** Division numbers, `min <= max`; either may be absent (an open end reaches the grid's edge). */
  min?: number;
  max?: number;
  onChange: (min: number | undefined, max: number | undefined) => void;
  ariaLabel: string;
  disabled?: boolean;
}

/**
 * A range's end divisions, worse first ("Gold 3", "Diamond 1"): none for no range, one when both ends are the same
 * division. An open end reaches the grid's edge.
 */
export function divisionRangeEnds(grid: DivisionGridLike, min?: number, max?: number): DivisionTier[] {
  if (min === undefined && max === undefined) return [];
  const numbers = grid.tiers.map((tier) => tier.number);
  const low = min ?? Math.min(...numbers);
  const high = max ?? Math.max(...numbers);
  return grid.tiers
    .filter((tier) => tier.number === low || tier.number === high)
    .sort((left, right) => left.rank_min - right.rank_min);
}

/**
 * A division range as one control: the grid's tiers in rows (Champion 1..5, Grandmaster 1..5, ...), best first.
 * The first click picks one division, the second closes the range; a row's name picks the whole row. Grids number
 * their tiers in either direction, but always monotonically by rank, so a number range is a contiguous rank range.
 */
export function DivisionRangePicker({ grid, min, max, onChange, ariaLabel, disabled }: Readonly<DivisionRangePickerProps>) {
  const t = useTranslations("common");
  const rows = useMemo(() => tierRows(grid), [grid]);
  const [open, setOpen] = useState(false);
  // The range's first end while the second is being picked, and the tier the pointer or focus previews it on.
  const [anchor, setAnchor] = useState<number | null>(null);
  const [preview, setPreview] = useState<number | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);

  const numbers = grid.tiers.map((tier) => tier.number);
  const selected: [number, number] | null =
    min === undefined && max === undefined ? null : [min ?? Math.min(...numbers), max ?? Math.max(...numbers)];
  const shown: [number, number] | null =
    anchor === null ? selected : [Math.min(anchor, preview ?? anchor), Math.max(anchor, preview ?? anchor)];
  const inShown = (n: number) => shown !== null && n >= shown[0] && n <= shown[1];
  const isEnd = (n: number) => shown !== null && (n === shown[0] || n === shown[1]);

  const ends = divisionRangeEnds(grid, min, max);
  const labelText = ends.length === 0 ? t("anyDivision") : ends.map((tier) => tier.name).join(" – ");
  const focusNumber = anchor ?? selected?.[0] ?? rows[0]?.cells[0]?.tier.number;

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    setAnchor(null);
    setPreview(null);
  };
  const pick = (n: number) => {
    if (anchor === null) {
      setAnchor(n);
      onChange(n, n);
      return;
    }
    onChange(Math.min(anchor, n), Math.max(anchor, n));
    onOpenChange(false);
  };
  const pickRow = (row: TierRow) => {
    const rowNumbers = row.cells.map((cell) => cell.tier.number);
    onChange(Math.min(...rowNumbers), Math.max(...rowNumbers));
    onOpenChange(false);
  };

  // Arrows walk the grid: Left/Right along a row (its name first), Up/Down keep the column.
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = ARROWS[event.key];
    const row = (event.target as HTMLElement).closest<HTMLElement>("[data-row]");
    if (!step || !row) return;
    event.preventDefault();
    const rowEls = [...event.currentTarget.querySelectorAll<HTMLElement>("[data-row]")];
    const buttons = (el: HTMLElement) => [...el.querySelectorAll<HTMLButtonElement>("button")];
    const col = buttons(row).indexOf(event.target as HTMLButtonElement);
    const next = buttons(rowEls[clamp(rowEls.indexOf(row) + step[0], rowEls.length - 1)]);
    next[clamp(col + step[1], next.length - 1)]?.focus();
  };

  const icon = (tier: DivisionTier) => (
    <Image src={tier.icon_url} alt="" width={20} height={20} className="size-5 shrink-0 select-none object-contain" />
  );

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled || rows.length === 0}
          aria-haspopup="dialog"
          aria-label={`${ariaLabel}: ${labelText}`}
          title={labelText}
          className="group/trigger w-full justify-between"
        >
          <span className="flex min-w-0 items-center gap-1.5 overflow-hidden">
            {ends.length === 0 ? <span className="truncate">{labelText}</span> : null}
            {ends.map((tier, index) => (
              <span key={tier.number} className="flex min-w-0 items-center gap-1.5">
                {index > 0 ? <span aria-hidden className="text-[color:var(--aqt-fg-dim)]">–</span> : null}
                {icon(tier)}
                <span className="truncate">{tier.name}</span>
              </span>
            ))}
          </span>
          <ChevronDown aria-hidden className={triggerChevronClass} />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        aria-label={ariaLabel}
        className="w-auto max-w-[calc(100vw-2rem)] max-h-[min(30rem,var(--radix-popover-content-available-height))] overflow-y-auto p-3"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          gridRef.current?.querySelector<HTMLButtonElement>('[data-tier][tabindex="0"]')?.focus();
        }}
      >
        <div className="mb-2 flex items-center justify-between gap-3">
          <p className="text-caption text-[color:var(--aqt-fg-dim)]" aria-live="polite">
            {anchor === null ? t("divisionRange.pickFirst") : t("divisionRange.pickSecond")}
          </p>
          <Button
            type="button"
            variant="ghost"
            size="xs"
            disabled={selected === null}
            onClick={() => {
              onChange(undefined, undefined);
              onOpenChange(false);
            }}
          >
            {t("anyDivision")}
          </Button>
        </div>
        <div
          ref={gridRef}
          className="grid gap-y-1 sm:grid-cols-[max-content_minmax(0,auto)] sm:items-center sm:gap-x-2"
          onKeyDown={onKeyDown}
          onMouseLeave={() => setPreview(null)}
        >
          {rows.map((row) => {
            const rowOn = row.cells.some((cell) => inShown(cell.tier.number));
            // Overwatch's crests carry their own step: the cells are the crests. A row sharing one emblem (League,
            // Deadlock) wears it on its name and spells the steps out.
            const sharedEmblem =
              row.cells[0].step !== null && row.cells.every((cell) => cell.tier.icon_url === row.cells[0].tier.icon_url);
            return (
              <div
                key={`${row.name}-${row.cells[0].tier.number}`}
                data-row=""
                role="group"
                aria-label={row.name}
                className="contents"
              >
                <Button
                  type="button"
                  variant="ghost"
                  size="label"
                  tabIndex={-1}
                  aria-label={t("divisionRange.wholeRow", { name: row.name })}
                  onClick={() => pickRow(row)}
                  className={cn(
                    "h-7 justify-self-start rounded-md px-1.5 sm:h-9",
                    rowOn ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-dim)]"
                  )}
                >
                  {sharedEmblem ? icon(row.cells[0].tier) : null}
                  {row.name}
                </Button>
                <div className="flex flex-wrap gap-1">
                  {row.cells.map(({ tier, step }) => {
                    const on = inShown(tier.number);
                    return (
                      <Button
                        key={tier.number}
                        type="button"
                        // The chosen span wears the teal tint of a chosen option; its two ends a firmer rim.
                        variant={on ? "accent" : "ghost"}
                        size="icon"
                        data-tier=""
                        tabIndex={tier.number === focusNumber ? 0 : -1}
                        aria-pressed={on}
                        aria-label={tier.name}
                        title={tier.name}
                        onClick={() => pick(tier.number)}
                        onMouseEnter={() => setPreview(tier.number)}
                        onFocus={() => setPreview(tier.number)}
                        className={cn(
                          "w-auto min-w-9 gap-1 px-1.5 text-label font-semibold tabular-nums",
                          !on && "text-[color:var(--aqt-fg-muted)]",
                          isEnd(tier.number) && "border-[color:color-mix(in_srgb,var(--aqt-teal)_55%,transparent)]"
                        )}
                      >
                        {sharedEmblem ? <span>{step}</span> : icon(tier)}
                      </Button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}
