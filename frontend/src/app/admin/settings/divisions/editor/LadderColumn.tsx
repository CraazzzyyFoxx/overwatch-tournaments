"use client";

import { useEffect, useRef, type ReactNode } from "react";
import Image from "@/components/ui/image";
import { ChevronDown, ChevronUp, Merge, Scissors } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { RowButton } from "@/components/ui/row-button";
import { cn } from "@/lib/utils";

import {
  ladderOwners,
  nativeSize,
  rankLabel,
  type Action,
  type Band,
  type Ladder,
  type Scale
} from "./draftReducer";

export interface LadderColumnProps {
  /** The discipline's native ladder this column draws, one row per rank. */
  ladder: Ladder;
  /** The game's short name ("OW") the column heading names its ladder by. */
  game: string;
  bands: Band[];
  scale: Scale;
  /** Slug of the band in `?band=`, drawn highlighted. */
  selectedSlug: string | null;
  editable: boolean;
  /** The saved version stores no native link, so what is drawn is the rank-range fallback. */
  implicitLinks: boolean;
  onSelect: (slug: string) => void;
  dispatch: (action: Action) => void;
}

/**
 * The native ladder, one row per rank, each labelled with the division it lands in
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
  ladder,
  game,
  bands,
  scale,
  selectedSlug,
  editable,
  implicitLinks,
  onSelect,
  dispatch
}: Readonly<LadderColumnProps>) {
  const t = useTranslations("adminSettings.divisions");
  const listRef = useRef<HTMLOListElement>(null);
  const owners = ladderOwners(ladder, bands);
  const gaps = owners.filter((owner) => owner === null).length;
  const onLadder = scale === "ladder";

  useEffect(() => {
    listRef.current
      ?.querySelector("[data-selected-start]")
      ?.scrollIntoView?.({ block: "nearest" });
  }, [selectedSlug]);

  const hint = !editable
    ? t("ladder.hintImmutable")
    : onLadder
      ? t("ladder.hintLadder")
      : t("ladder.hintCustom", { game });

  return (
    <Card className="flex max-h-[calc(100vh-13rem)] flex-col xl:sticky xl:top-4">
      <h2 className="border-b border-border px-3 py-2 font-display text-sm font-semibold">
        {t("ladder.title", { game })}
      </h2>

      <p className="px-3 pt-2 text-xs text-muted-foreground">{hint}</p>
      {implicitLinks && !onLadder ? (
        <p className="px-3 pt-1 text-xs text-muted-foreground">{t("ladder.noLinks")}</p>
      ) : null}

      <ol
        ref={listRef}
        aria-label={t("ladder.aria")}
        className="min-h-0 flex-1 overflow-y-auto p-2"
      >
        {ladder.ranks.map((rank, index) => {
          const owner = owners[index];
          const band = owner === null ? null : bands[owner];
          const above = index > 0 ? owners[index - 1] : null;
          const startsRun = index === 0 || above !== owner;
          const selected = band !== null && band.slug === selectedSlug;

          const boundary = editable && index > 0 && startsRun;
          // -1 hands the rank above the boundary down to this row's side; +1 hands this rank up.
          const canRaise = boundary && (!onLadder || (above !== null && nativeSize(bands[above]) >= 2));
          const canLower = boundary && (!onLadder || (band !== null && nativeSize(band) >= 2));
          const canJoin = boundary && onLadder && band !== null && above !== null;
          const canCut = editable && onLadder && !startsRun;
          const into = (target: number | null, moving: number) =>
            target === null
              ? t("ladder.unlinkRank", { rank: rankLabel(ladder, moving) })
              : t("ladder.moveRank", { rank: rankLabel(ladder, moving), target: bands[target].name });

          return (
            <li
              key={rank.slug}
              data-selected-start={selected && startsRun ? "" : undefined}
              aria-current={selected ? "true" : undefined}
              className={cn(
                "group relative flex h-7 items-center gap-2 border-l-2 pl-2 pr-1",
                startsRun && index > 0 && "mt-1",
                owner === null
                  ? "border-l-transparent"
                  : owner % 2 === 0
                    ? "border-l-foreground/20"
                    : "border-l-foreground/50",
                selected && "bg-accent/40"
              )}
            >
              <RowButton
                disabled={band === null}
                onClick={() => band && onSelect(band.slug)}
                className="flex min-w-0 flex-1 items-center gap-2 rounded-sm"
                aria-label={band ? t("ladder.rankIn", { rank: rank.name, division: band.name }) : t("ladder.rankUnlinked", { rank: rank.name })}
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
              </RowButton>

              {startsRun ? (
                <span
                  className={cn(
                    "max-w-[55%] truncate text-xs font-medium",
                    band === null && "text-warning"
                  )}
                  title={band ? `${band.number}. ${band.name}` : undefined}
                >
                  {band ? `${band.number}. ${band.name}` : t("ladder.notLinked")}
                </span>
              ) : null}

              {canRaise || canLower || canJoin || canCut ? (
                <span className="absolute inset-y-0 right-0 flex items-center gap-0.5 bg-gradient-to-r from-transparent via-card via-40% to-card pl-6 pr-1 opacity-0 group-focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100">
                  {canRaise ? (
                    <NudgeButton
                      label={into(owner, index - 1)}
                      onClick={() => dispatch({ type: "nudge", rank: index, delta: -1 })}
                    >
                      <ChevronUp aria-hidden />
                    </NudgeButton>
                  ) : null}
                  {canLower ? (
                    <NudgeButton
                      label={into(above, index)}
                      onClick={() => dispatch({ type: "nudge", rank: index, delta: 1 })}
                    >
                      <ChevronDown aria-hidden />
                    </NudgeButton>
                  ) : null}
                  {canJoin ? (
                    <NudgeButton
                      label={t("ladder.join", { from: band!.name, into: bands[above!].name })}
                      onClick={() => dispatch({ type: "merge", bandIndex: owner!, into: "up" })}
                    >
                      <Merge aria-hidden />
                    </NudgeButton>
                  ) : null}
                  {canCut ? (
                    <NudgeButton
                      label={t("ladder.startDivision", { rank: rank.name })}
                      onClick={() => dispatch({ type: "splitAt", rank: index })}
                    >
                      <Scissors aria-hidden />
                    </NudgeButton>
                  ) : null}
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>

      {gaps > 0 ? (
        <p className="border-t border-border px-3 py-2 text-xs text-warning">
          {t("ladder.gaps", { count: gaps })}
        </p>
      ) : null}
    </Card>
  );
}

function NudgeButton({
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
