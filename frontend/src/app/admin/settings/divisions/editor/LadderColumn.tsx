"use client";

import { ChevronDown, ChevronUp } from "lucide-react";

import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { bandSize, rankLabel, RANK_COUNT, type Action, type Band } from "./draftReducer";

export interface LadderColumnProps {
  bands: Band[];
  /** Slug of the band in `?band=`, drawn highlighted. */
  selectedSlug: string | null;
  editable: boolean;
  onSelect: (slug: string) => void;
  dispatch: (action: Action) => void;
}

/**
 * The ladder as the editing surface (F12 ·2).
 *
 * This is the idea the spreadsheet grid and `OwRankRangePicker` gave up on:
 * the user does not type rank numbers, they cut the ladder. Clicking a rank
 * starts a division there; the arrows move a boundary one rank at a time, and
 * a boundary belongs to two bands at once — so "no gaps, no overlaps" is a
 * property of the controls, not a validation message after the fact.
 *
 * Its own scroll container on purpose: 45 ranks stacked next to the table is
 * what stretched the hi-fi reference to ~2000px of page height.
 */
export function LadderColumn({
  bands,
  selectedSlug,
  editable,
  onSelect,
  dispatch
}: Readonly<LadderColumnProps>) {
  return (
    <div className="flex max-h-[calc(100vh-13rem)] flex-col rounded-xl border border-border bg-card xl:sticky xl:top-4">
      <div className="flex items-baseline justify-between gap-2 border-b border-border px-3 py-2">
        <h2 className="font-display text-sm font-semibold">OW ladder</h2>
        <span className={cn(EYEBROW_CLASS, "font-mono tabular-nums")}>{RANK_COUNT} ranks</span>
      </div>

      <p className="px-3 pt-2 text-xs text-muted-foreground">
        {editable
          ? "Click a rank to start a new division there. The arrows move a boundary one rank at a time."
          : "This version is immutable, so the ladder is shown as it was published."}
      </p>

      <ul className="min-h-0 flex-1 overflow-y-auto p-2">
        {bands.map((band, index) => {
          const selected = band.slug === selectedSlug;
          return (
            <li
              key={band.slug}
              className={cn(
                "mt-1 border-l-2 pl-2 first:mt-0",
                selected ? "border-l-primary bg-primary/5" : "border-l-border"
              )}
            >
              <div className="flex items-start gap-1">
                <button
                  type="button"
                  onClick={() => onSelect(band.slug)}
                  className="min-w-0 flex-1 py-1 text-left"
                >
                  <span
                    className={cn(
                      "block truncate text-xs font-semibold uppercase tracking-wider",
                      selected ? "text-primary" : "text-foreground"
                    )}
                  >
                    {band.number}. {band.name}
                  </span>
                </button>

                {editable ? (
                  <span className="flex shrink-0 flex-col">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-5"
                      aria-label={`Raise the top of ${band.name} by one rank`}
                      disabled={index === 0 || bandSize(bands[index - 1]) < 2}
                      onClick={() =>
                        dispatch({
                          type: "moveBoundary",
                          bandIndex: index,
                          edge: "ceiling",
                          delta: -1
                        })
                      }
                    >
                      <ChevronUp aria-hidden className="size-3" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-5"
                      aria-label={`Lower the top of ${band.name} by one rank`}
                      disabled={index === 0 || bandSize(band) < 2}
                      onClick={() =>
                        dispatch({
                          type: "moveBoundary",
                          bandIndex: index,
                          edge: "ceiling",
                          delta: 1
                        })
                      }
                    >
                      <ChevronDown aria-hidden className="size-3" />
                    </Button>
                  </span>
                ) : null}
              </div>

              <ul className="flex flex-wrap items-center gap-x-1 pb-1 font-mono text-xs text-muted-foreground">
                {Array.from({ length: bandSize(band) }, (_unused, offset) => {
                  const rank = band.owFrom + offset;
                  return (
                    <li key={rank}>
                      {/* The band's own first rank IS the boundary above it —
                          there is nothing to split there, so it is text. */}
                      {offset === 0 || !editable ? (
                        <span>{rankLabel(rank)}</span>
                      ) : (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-5 px-1 font-mono text-xs font-normal text-muted-foreground"
                          aria-label={`Start a new division at ${rankLabel(rank)}`}
                          onClick={() => dispatch({ type: "splitAt", rank })}
                        >
                          {rankLabel(rank)}
                        </Button>
                      )}
                    </li>
                  );
                })}
              </ul>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
