"use client";

import { useRef, useState } from "react";
import { ChevronDown, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

import { overlapRange, type MappingChoice, type MappingRow, type MappingTarget } from "./autoMap";
import { rankRangeLabel, type Band } from "./draftReducer";

export interface MappingTargetPickerProps {
  row: MappingRow;
  bands: Band[];
  target: MappingTarget | null;
  /** `null` goes back to the automatic mapping. */
  onChange: (choice: MappingChoice | null) => void;
}

/** "38. Bronze 3", plus "· over 36–40" when the players spread over a range. */
export function targetSummary(target: MappingTarget | null): string {
  if (!target) return "not chosen";
  const landing = `${target.primary.number}. ${target.primary.name}`;
  if (target.range.length === 1) return landing;
  return `${landing} · over ${target.range[0].number}\u2013${target.range.at(-1)!.number}`;
}

/**
 * Where one old division's players go in the draft: a range of divisions they
 * spread over, and the one they land in.
 *
 * Click a division to send the players there alone; click a second one to
 * spread them over every division between the two. The dot on a row of the
 * range moves where they land. A SPLIT row opens with its tied divisions
 * proposed, so resolving it is one click on a dot.
 */
export function MappingTargetPicker({ row, bands, target, onChange }: Readonly<MappingTargetPickerProps>) {
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<number | null>(null);
  const focusRef = useRef<HTMLButtonElement>(null);
  const name = row.source.name;

  // The range drawn: the target's, else the tie a SPLIT row asks to resolve.
  const shown = target?.range ?? overlapRange(row);
  const from = shown.length > 0 ? bands.findIndex((band) => band.slug === shown[0].slug) : -1;
  const to = from === -1 ? -1 : from + shown.length - 1;
  const proposed = target === null && shown.length > 1;
  const focusIndex = target ? bands.findIndex((band) => band.slug === target.primary.slug) : from;

  const toggle = (next: boolean) => {
    setOpen(next);
    if (!next) setAnchor(null);
  };

  const pick = (index: number) => {
    const band = bands[index];
    if (band.id === undefined) return;
    const anchored = anchor === null ? undefined : bands[anchor];
    if (anchored?.id === undefined || anchor === index) {
      onChange({ targets: [band.id], primary: band.id });
      setAnchor(anchor === index ? null : index);
      return;
    }
    onChange({ targets: [anchored.id, band.id], primary: anchored.id });
    setAnchor(null);
  };

  const land = (index: number) => {
    const ids = [bands[from]?.id, bands[to]?.id, bands[index]?.id];
    if (ids.some((id) => id === undefined)) return;
    onChange({ targets: [ids[0]!, ids[1]!], primary: ids[2]! });
    setAnchor(null);
  };

  const hint =
    anchor !== null
      ? `Click another division to spread ${name} over the range, or the same one to keep it alone.`
      : proposed
        ? "The overlap is tied — pick with a dot where the players land, or click a division to choose another."
        : "Click a division to send the players there; click a second one to spread them over the range between.";

  const note = !target
    ? null
    : target.range.length === 1
      ? `Every player of ${name} lands in ${target.primary.name}.`
      : `${target.byOverlap ? "Shares follow the rank overlap." : "Shares are even — the range reaches past the rank overlap."} The dot marks where players land.`;

  return (
    <Popover open={open} onOpenChange={toggle}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          aria-label={`Target divisions for ${name}: ${targetSummary(target)}`}
          className="h-8 w-full min-w-56 justify-between gap-2 px-2 font-normal"
        >
          {target ? (
            <span className="flex min-w-0 items-baseline gap-1.5">
              <span className="truncate">
                {target.primary.number}. {target.primary.name}
              </span>
              <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                {target.range.length > 1
                  ? `over ${target.range[0].number}\u2013${target.range.at(-1)!.number}`
                  : rankRangeLabel(target.primary)}
              </span>
            </span>
          ) : (
            <span className="text-warning">Choose where players go</span>
          )}
          <ChevronDown aria-hidden className="size-3 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-[26rem] p-0"
        aria-label={`Target divisions for ${name}`}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          focusRef.current?.focus();
        }}
      >
        <div className="border-b border-border px-3 py-2">
          <p className="text-sm font-medium">
            {name} <span className="font-mono text-xs text-muted-foreground">{rankRangeLabel(row.source)}</span>
          </p>
          <p className="text-xs text-muted-foreground" aria-live="polite">
            {hint}
          </p>
        </div>

        <ol className="max-h-80 overflow-y-auto p-1">
          {bands.map((band, index) => {
            const inRange = index >= from && index <= to;
            const landing = target?.primary.slug === band.slug;
            const share = inRange
              ? target
                ? target.weights[index - from]
                : row.candidates.find((candidate) => candidate.band.slug === band.slug)?.weight
              : undefined;
            return (
              <li
                key={band.slug}
                className={cn(
                  "flex items-center gap-1 rounded-md border",
                  index === anchor
                    ? "border-primary"
                    : proposed && inRange
                      ? "border-dashed border-warning/60"
                      : "border-transparent",
                  inRange && !proposed && "bg-primary/10"
                )}
              >
                <button
                  ref={index === focusIndex ? focusRef : undefined}
                  type="button"
                  onClick={() => pick(index)}
                  className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="w-6 shrink-0 text-right font-mono text-xs tabular-nums text-muted-foreground">
                    {band.number}
                  </span>
                  <span className={cn("min-w-0 flex-1 truncate", landing && "font-semibold")}>
                    {band.name}
                  </span>
                  <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                    {rankRangeLabel(band)}
                  </span>
                </button>
                <span
                  className={cn(
                    "w-10 shrink-0 text-right font-mono text-xs tabular-nums",
                    target ? "text-foreground" : "text-muted-foreground"
                  )}
                >
                  {share === undefined ? null : `${Math.round(share * 100)}%`}
                </span>
                {inRange && shown.length > 1 ? (
                  <button
                    type="button"
                    aria-pressed={landing}
                    aria-label={`Players of ${name} land in ${band.name}`}
                    title={`Players of ${name} land in ${band.name}`}
                    onClick={() => land(index)}
                    className="mr-1 grid size-6 shrink-0 place-items-center rounded-full hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span
                      className={cn(
                        "size-2.5 rounded-full border",
                        landing ? "border-primary bg-primary" : "border-muted-foreground"
                      )}
                    />
                  </button>
                ) : (
                  <span aria-hidden className="mr-1 size-6 shrink-0" />
                )}
              </li>
            );
          })}
        </ol>

        <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-2">
          <p className="min-w-0 text-xs text-muted-foreground">{note ?? "Nothing chosen yet."}</p>
          {row.kind === "auto" && target?.manual ? (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 shrink-0 px-2 text-xs"
              onClick={() => {
                onChange(null);
                setAnchor(null);
              }}
            >
              <RotateCcw aria-hidden className="size-3" />
              Automatic
            </Button>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  );
}
