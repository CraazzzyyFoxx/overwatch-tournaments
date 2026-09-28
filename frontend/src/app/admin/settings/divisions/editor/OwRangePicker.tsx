"use client";

import { useState } from "react";
import { ChevronDown, Unlink } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { TIER_NUMBERS } from "@/lib/divisions/ow-ladder";
import { cn } from "@/lib/utils";

import { ladderOwners, owRangeLabel, RANK_COUNT, rankLabel, type Band } from "./draftReducer";

/** One grid row per OW division (Champion … Bronze), one column per tier. */
const ROWS = Array.from({ length: RANK_COUNT / TIER_NUMBERS.length }, (_, row) => row);

export interface OwRangePickerProps {
  bands: Band[];
  bandIndex: number;
  onLink: (from: number, to: number) => void;
  onUnlink: () => void;
}

/**
 * Which OW ranks land in one division of a custom-scale grid.
 *
 * Click the first rank, then the last (the same one twice for a single rank);
 * hovering previews the run. Ranks already in another division are drawn
 * filled and say whose they are — taking them is allowed, because the reducer
 * keeps the runs in division order by clipping the neighbours. Unlinked ranks
 * are dashed, so a gap in the ladder is visible from any row.
 */
export function OwRangePicker({ bands, bandIndex, onLink, onUnlink }: Readonly<OwRangePickerProps>) {
  const band = bands[bandIndex];
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<number | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);
  const owners = ladderOwners(bands);

  const edge = hovered ?? anchor;
  const [low, high] =
    anchor !== null && edge !== null
      ? [Math.min(anchor, edge), Math.max(anchor, edge)]
      : band.ow
        ? [band.ow.from, band.ow.to]
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
    onLink(Math.min(anchor, index), Math.max(anchor, index));
    toggle(false);
  };

  return (
    <Popover open={open} onOpenChange={toggle}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          aria-label={`OW ranks of ${band.name}: ${owRangeLabel(band)}`}
          className={cn(
            "h-8 w-full min-w-40 justify-between px-2 font-mono text-xs font-normal",
            !band.ow && "text-warning"
          )}
        >
          <span className="truncate">{owRangeLabel(band)}</span>
          <ChevronDown aria-hidden className="size-3 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto p-2" aria-label={`OW ranks of ${band.name}`}>
        <div className="flex flex-col gap-1" onMouseLeave={() => setHovered(null)}>
          {ROWS.map((row) => (
            <div
              key={row}
              // Literal 5: Tailwind cannot see an interpolated class; TIER_NUMBERS drives the cells.
              className="grid grid-cols-[92px_repeat(5,minmax(0,1fr))] items-center gap-1"
            >
              <span className="pr-2 text-xs text-muted-foreground">
                {rankLabel(row * TIER_NUMBERS.length).replace(/\s+\d+$/, "")}
              </span>
              {TIER_NUMBERS.map((tier, column) => {
                const index = row * TIER_NUMBERS.length + column;
                const owner = owners[index];
                const other = owner !== null && owner !== bandIndex ? bands[owner] : null;
                const inRange = low !== null && high !== null && index >= low && index <= high;
                const endpoint = index === low || index === high;
                const label = other ? `${rankLabel(index)}, now in ${other.name}` : rankLabel(index);
                return (
                  <button
                    key={tier}
                    type="button"
                    aria-pressed={inRange}
                    aria-label={label}
                    title={label}
                    onClick={() => pick(index)}
                    onMouseEnter={() => setHovered(index)}
                    onFocus={() => setHovered(index)}
                    className={cn(
                      "h-7 min-w-9 rounded-md border text-xs tabular-nums transition-colors",
                      endpoint
                        ? "border-primary bg-primary text-primary-foreground"
                        : inRange
                          ? "border-primary/40 bg-primary/15"
                          : other
                            ? "border-transparent bg-muted text-muted-foreground hover:border-border"
                            : owner === null
                              ? "border-dashed border-warning/60 hover:bg-muted"
                              : "border-transparent hover:border-border hover:bg-muted"
                    )}
                  >
                    {tier}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
        <div className="mt-2 flex items-start justify-between gap-2 border-t border-border pt-2">
          <p className="max-w-56 text-xs text-muted-foreground" aria-live="polite">
            {anchor === null
              ? "Click the first rank, then the last. Ranks taken from another division move here."
              : `From ${rankLabel(anchor)} — click the other end, or the same rank again.`}
          </p>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 shrink-0 px-2 text-xs"
            disabled={!band.ow}
            onClick={() => {
              onUnlink();
              toggle(false);
            }}
          >
            <Unlink aria-hidden className="size-3" />
            Unlink
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
