"use client";

import { useEffect, useRef, type ReactNode } from "react";
import Image from "next/image";
import { ChevronDown, ChevronUp, Merge, Scissors } from "lucide-react";

import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import {
  ladderOwners,
  LADDER,
  owSize,
  RANK_COUNT,
  rankLabel,
  type Action,
  type Band,
  type Scale
} from "./draftReducer";

export interface LadderColumnProps {
  bands: Band[];
  scale: Scale;
  /** Slug of the band in `?band=`, drawn highlighted. */
  selectedSlug: string | null;
  editable: boolean;
  /** The saved version stores no OW link, so what is drawn is the rank-range fallback. */
  implicitLinks: boolean;
  onSelect: (slug: string) => void;
  dispatch: (action: Action) => void;
}

/**
 * The OW ladder, one row per rank, each labelled with the division it lands in
 * (F12 ·2).
 *
 * One row per rank rather than one block per division, so the column costs the
 * same 45 short rows whether the grid has 3 divisions or 45 — and every
 * boundary stays reachable. The controls sit on the row that starts a run,
 * which is where the boundary above it is:
 *  - both scales: the arrows hand one rank across that boundary;
 *  - ladder scale: join the division into the one above, or cut a new one at
 *    any other rank. A one-rank division is never stuck — it can always join.
 *  - custom scale: a division may give up its last rank and a rank may land
 *    nowhere; the column flags those rows instead of refusing the move.
 *
 * Its own scroll container: the ladder next to the table would otherwise set
 * the page height.
 */
export function LadderColumn({
  bands,
  scale,
  selectedSlug,
  editable,
  implicitLinks,
  onSelect,
  dispatch
}: Readonly<LadderColumnProps>) {
  const listRef = useRef<HTMLOListElement>(null);
  const owners = ladderOwners(bands);
  const gaps = owners.filter((owner) => owner === null).length;
  const onLadder = scale === "ladder";

  useEffect(() => {
    listRef.current
      ?.querySelector("[data-selected-start]")
      ?.scrollIntoView?.({ block: "nearest" });
  }, [selectedSlug]);

  const hint = !editable
    ? "This version is immutable, so the ladder is shown as it was published."
    : onLadder
      ? "Rank ranges follow the ladder. Hover a rank to cut a new division there, or join a division to the one above. The arrows move a boundary one rank."
      : "Where each OW rank lands. The arrows move a boundary one rank; link a whole run from the OW ranks column.";

  return (
    <div className="flex max-h-[calc(100vh-13rem)] flex-col rounded-xl border border-border bg-card xl:sticky xl:top-4">
      <div className="flex items-baseline justify-between gap-2 border-b border-border px-3 py-2">
        <h2 className="font-display text-sm font-semibold">OW ladder</h2>
        <span className={cn(EYEBROW_CLASS, "font-mono tabular-nums")}>{RANK_COUNT} ranks</span>
      </div>

      <p className="px-3 pt-2 text-xs text-muted-foreground">{hint}</p>
      {implicitLinks && !onLadder ? (
        <p className="mx-2 mt-2 rounded-md border border-border bg-muted/40 px-2 py-1.5 text-xs text-muted-foreground">
          This version stores no OW links, so OW ranks resolve by rank range — that is what is
          drawn. Saving stores the links as shown.
        </p>
      ) : null}

      <ol
        ref={listRef}
        aria-label="OW ranks and the division each lands in"
        className="min-h-0 flex-1 overflow-y-auto p-2"
      >
        {LADDER.map((rank, index) => {
          const owner = owners[index];
          const band = owner === null ? null : bands[owner];
          const above = index > 0 ? owners[index - 1] : null;
          const startsRun = index === 0 || above !== owner;
          const selected = band !== null && band.slug === selectedSlug;

          const boundary = editable && index > 0 && startsRun;
          // -1 hands the rank above the boundary down to this row's side; +1 hands this rank up.
          const canRaise = boundary && (!onLadder || (above !== null && owSize(bands[above]) >= 2));
          const canLower = boundary && (!onLadder || (band !== null && owSize(band) >= 2));
          const canJoin = boundary && onLadder && band !== null && above !== null;
          const canCut = editable && onLadder && !startsRun;
          const into = (target: number | null, moving: number) =>
            target === null
              ? `Unlink ${rankLabel(moving)}`
              : `Move ${rankLabel(moving)} into ${bands[target].name}`;

          return (
            <li
              key={rank.slug ?? index}
              data-selected-start={selected && startsRun ? "" : undefined}
              className={cn(
                "group relative flex h-7 items-center gap-2 border-l-2 pl-2 pr-1",
                startsRun && index > 0 && "mt-1",
                band === null
                  ? "border-l-warning/70 bg-warning/5"
                  : selected
                    ? "border-l-primary bg-primary/10"
                    : owner! % 2 === 0
                      ? "border-l-foreground/20"
                      : "border-l-foreground/50"
              )}
            >
              <button
                type="button"
                disabled={band === null}
                onClick={() => band && onSelect(band.slug)}
                className="flex min-w-0 flex-1 items-center gap-2 rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default"
                aria-label={
                  band ? `${rank.name}, in ${band.name}` : `${rank.name}, in no division`
                }
              >
                <Image
                  src={rank.icon_url}
                  alt=""
                  width={16}
                  height={16}
                  unoptimized
                  className="size-4 shrink-0 object-contain"
                />
                <span className="truncate text-xs">{rank.name}</span>
              </button>

              {startsRun ? (
                <span
                  className={cn(
                    "max-w-[55%] truncate rounded px-1.5 py-0.5 text-xs font-medium",
                    band === null
                      ? "text-warning"
                      : selected
                        ? "bg-primary/15 text-primary"
                        : "bg-muted text-foreground"
                  )}
                  title={band ? `${band.number}. ${band.name}` : undefined}
                >
                  {band ? `${band.number}. ${band.name}` : "Not linked"}
                </span>
              ) : null}

              {canRaise || canLower || canJoin || canCut ? (
                <span className="absolute inset-y-0 right-0 flex items-center gap-0.5 bg-gradient-to-r from-transparent via-card via-40% to-card pl-6 pr-1 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100">
                  {canRaise ? (
                    <RowButton
                      label={into(owner, index - 1)}
                      onClick={() => dispatch({ type: "nudge", rank: index, delta: -1 })}
                    >
                      <ChevronUp aria-hidden />
                    </RowButton>
                  ) : null}
                  {canLower ? (
                    <RowButton
                      label={into(above, index)}
                      onClick={() => dispatch({ type: "nudge", rank: index, delta: 1 })}
                    >
                      <ChevronDown aria-hidden />
                    </RowButton>
                  ) : null}
                  {canJoin ? (
                    <RowButton
                      label={`Join ${band!.name} into ${bands[above!].name}`}
                      onClick={() => dispatch({ type: "merge", bandIndex: owner!, into: "up" })}
                    >
                      <Merge aria-hidden />
                    </RowButton>
                  ) : null}
                  {canCut ? (
                    <RowButton
                      label={`Start a new division at ${rank.name}`}
                      onClick={() => dispatch({ type: "splitAt", rank: index })}
                    >
                      <Scissors aria-hidden />
                    </RowButton>
                  ) : null}
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>

      {gaps > 0 ? (
        <p className="border-t border-border px-3 py-2 text-xs text-warning">
          {gaps} {gaps === 1 ? "rank lands" : "ranks land"} in no division
        </p>
      ) : null}
    </div>
  );
}

function RowButton({
  label,
  onClick,
  children
}: Readonly<{ label: string; onClick: () => void; children: ReactNode }>) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-6 [&_svg]:size-3.5"
      aria-label={label}
      title={label}
      onClick={onClick}
    >
      {children}
    </Button>
  );
}
