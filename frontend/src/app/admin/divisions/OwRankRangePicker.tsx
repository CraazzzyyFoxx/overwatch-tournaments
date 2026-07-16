"use client";

import { useCallback, useMemo, useState } from "react";
import { ChevronDown, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { OW2_DIVISIONS_DESC, defaultRankForCell } from "@/lib/ow-rank-mapping";

type OwRankRangePickerProps = {
  min: number | null;
  max: number | null;
  disabled?: boolean;
  onChange: (min: number | null, max: number | null) => void;
};

function divisionLabel(division: string): string {
  return `${division.charAt(0).toUpperCase()}${division.slice(1)}`;
}

function rankLabel(value: number | null): string | null {
  if (value == null) return null;
  for (const division of OW2_DIVISIONS_DESC) {
    for (let tier = 1; tier <= 5; tier++) {
      if (defaultRankForCell(division, tier) === value) {
        return `${divisionLabel(division)} ${tier}`;
      }
    }
  }
  return String(value);
}

/**
 * Single-control OW2 rank range picker (DateRange-style).
 *
 * Click a rank to set a single-rank range (min = max, popover stays open);
 * click a second rank to extend it into a full range (popover closes). While
 * one endpoint is anchored, hovering previews the prospective range. The value
 * is always stored ordered (`min` <= `max`); the backend treats the pair as an
 * unordered interval either way.
 */
export function OwRankRangePicker({ min, max, disabled, onChange }: OwRankRangePickerProps) {
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<number | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);

  const committedLow = min != null && max != null ? Math.min(min, max) : (min ?? max);
  const committedHigh = min != null && max != null ? Math.max(min, max) : (min ?? max);

  // Preview takes over while an anchor is set and another cell is hovered.
  const [previewLow, previewHigh] = useMemo(() => {
    if (anchor != null && hovered != null) {
      return [Math.min(anchor, hovered), Math.max(anchor, hovered)];
    }
    if (anchor != null) return [anchor, anchor];
    return [committedLow, committedHigh];
  }, [anchor, hovered, committedLow, committedHigh]);

  const label = useMemo(() => {
    if (committedLow == null || committedHigh == null) return null;
    const low = rankLabel(committedLow);
    const high = rankLabel(committedHigh);
    return committedLow === committedHigh ? low : `${low} – ${high}`;
  }, [committedLow, committedHigh]);

  const handleOpenChange = useCallback((next: boolean) => {
    setOpen(next);
    if (!next) {
      setAnchor(null);
      setHovered(null);
    }
  }, []);

  const handlePick = useCallback(
    (value: number) => {
      if (anchor == null) {
        // First click: commit a single-rank range and await an optional extension.
        setAnchor(value);
        onChange(value, value);
        return;
      }
      onChange(Math.min(anchor, value), Math.max(anchor, value));
      setAnchor(null);
      setHovered(null);
      setOpen(false);
    },
    [anchor, onChange]
  );

  const handleClear = useCallback(() => {
    onChange(null, null);
    setAnchor(null);
    setHovered(null);
    setOpen(false);
  }, [onChange]);

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          disabled={disabled}
          className={cn(
            "h-8 w-full justify-between px-2 text-xs font-normal",
            label == null && "text-muted-foreground"
          )}
        >
          <span className="truncate">{label ?? "—"}</span>
          <ChevronDown className="ml-1 h-3 w-3 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-2" align="start">
        <div className="space-y-1" onMouseLeave={() => setHovered(null)}>
          {OW2_DIVISIONS_DESC.map((division) => (
            <div
              key={division}
              className="grid grid-cols-[92px_repeat(5,minmax(0,1fr))] items-center gap-1"
            >
              <span className="pr-2 text-xs text-muted-foreground">{divisionLabel(division)}</span>
              {[1, 2, 3, 4, 5].map((tier) => {
                const value = defaultRankForCell(division, tier);
                const inRange =
                  previewLow != null &&
                  previewHigh != null &&
                  value >= previewLow &&
                  value <= previewHigh;
                const isEndpoint = value === previewLow || value === previewHigh;
                return (
                  <button
                    key={tier}
                    type="button"
                    title={`${divisionLabel(division)} ${tier} · ${value}`}
                    onClick={() => handlePick(value)}
                    onMouseEnter={() => setHovered(value)}
                    className={cn(
                      "h-7 min-w-9 rounded-md border text-xs tabular-nums transition-colors",
                      isEndpoint
                        ? "border-primary bg-primary text-primary-foreground"
                        : inRange
                          ? "border-primary/40 bg-primary/15"
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
        <div className="mt-2 flex items-center justify-between gap-2 border-t pt-2">
          <span className="text-xs text-muted-foreground">
            {anchor != null ? "Pick the other end of the range" : "Click start, then end"}
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs text-muted-foreground"
            onClick={handleClear}
            disabled={committedLow == null}
          >
            <X className="mr-1 h-3 w-3" />
            Clear
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
