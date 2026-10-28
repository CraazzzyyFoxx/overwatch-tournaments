"use client";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { useTranslations } from "next-intl";

import TeamName from "@/components/TeamName";
import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { mapWithModeName } from "@/lib/catalog/mode";
import { encounterSeatScore } from "@/lib/encounter/detail";
import { getEncounterWinner, isEncounterCompleted, isEncounterLive } from "@/lib/encounter/status";
import { seatAt, seatTeam, type DuelSlot } from "@/lib/encounter/seats";
import { cn } from "@/lib/utils";
import type { Encounter } from "@/types/encounter.types";

export type MatchCardProps = {
  encounter: Encounter;
  /** Mono eyebrow, e.g. "PLAYOFF · LOWER R3 · BO3 · 18:40" — built by the caller. */
  eyebrow: string;
  /** Where the card leads: the bracket node, or the encounter page. Absent → a plain, non-clickable card. */
  href?: string;
  /** Number of participant streams on air for this match, when known. */
  streamsCount?: number;
  /** `sm` — the overview's mini-bracket tile: no maps row, tighter rows. */
  size?: "md" | "sm";
  className?: string;
};

/**
 * One match as a card: eyebrow, two team rows with a bold score, and the maps
 * of the series. The whole card is one link. Used for live and upcoming
 * matches on the overview and the matches section; settled matches go in a
 * `MatchRow`.
 *
 * Markup mirrors the bracket node (`BracketView`'s `MatchCard`) so the two
 * surfaces speak one visual language; it is a separate component because the
 * bracket node carries hover-highlight and pointer bookkeeping this card has
 * no use for.
 */
export function MatchCard({
  encounter,
  eyebrow,
  href,
  streamsCount,
  size = "md",
  className
}: Readonly<MatchCardProps>) {
  const t = useTranslations();
  const live = isEncounterLive(encounter);
  const completed = isEncounterCompleted(encounter);
  const winner = getEncounterWinner(encounter);
  const scoreOne = seatAt(encounter.teams, 1)?.score ?? 0;
  const scoreTwo = seatAt(encounter.teams, 2)?.score ?? 0;
  const hasScore = completed || scoreOne !== 0 || scoreTwo !== 0;
  const rows = size === "sm" ? "h-8 text-caption" : "h-10 text-body";

  const row = (slot: DuelSlot) => {
    const seat = seatAt(encounter.teams, slot);
    const team = seatTeam(seat);
    const score = slot === 1 ? scoreOne : scoreTwo;
    const won = winner === slot;
    const lost = winner !== null && !won;
    return (
      <div
        className={cn(
          "flex items-center justify-between gap-2 px-2.5",
          rows,
          slot === 1 && "border-b border-[color:var(--aqt-border)]",
          won && "bg-[color:color-mix(in_srgb,var(--aqt-teal)_10%,transparent)] font-semibold text-[color:var(--aqt-fg)]",
          lost && "text-[color:var(--aqt-fg-dim)]",
          winner === null && "text-[color:var(--aqt-fg-muted)]"
        )}
      >
        <TeamName team={team} fallback={t("common.tbd")} size={size === "sm" ? "xs" : "sm"} />
        <span
          className={cn(
            "shrink-0 font-onest font-bold leading-none tabular-nums",
            size === "sm" ? "text-base" : "text-title",
            won ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-muted)]"
          )}
        >
          {hasScore ? score : "–"}
        </span>
      </div>
    );
  };

  const cardClassName = cn(
    "block overflow-hidden rounded-[10px] border bg-[color:var(--aqt-card)]",
    href &&
      "transition-colors hover:border-[color:var(--aqt-border-3)] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
    live
      ? "border-[color:color-mix(in_srgb,var(--aqt-rose)_45%,transparent)] shadow-[0_0_0_1px_color-mix(in_srgb,var(--aqt-rose)_30%,transparent)]"
      : "border-[color:var(--aqt-border)]",
    className
  );
  const body = (
    <>
      {/* The mini tile sits under a column heading that already names the
          round, so it carries no eyebrow of its own — only the live marker. */}
      {size === "md" || live ? (
        <div
          className={cn(
            eyebrowClass(),
            "flex items-center justify-between gap-2 border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.015)] px-2.5 py-1"
          )}
        >
          <span className="truncate">{size === "md" ? eyebrow : null}</span>
          {live ? (
            <TournamentStatusPill status="live" className="shrink-0 px-1.5 py-0">
              {t("common.live")}
              {streamsCount ? ` · ${streamsCount}` : null}
            </TournamentStatusPill>
          ) : null}
        </div>
      ) : null}
      {row(1)}
      {row(2)}
      {size === "md" && encounter.matches?.length > 0 ? (
        <ul className="flex flex-wrap gap-1 border-t border-[color:var(--aqt-border)] px-2.5 py-1.5">
          {encounter.matches.map((map) => {
            const mapScore = encounterSeatScore(map, encounter);
            const played = mapScore && (mapScore.one !== 0 || mapScore.two !== 0);
            return (
              <li
                key={map.id}
                className={cn(
                  "rounded border px-1.5 py-0.5 text-label",
                  played
                    ? "border-[color:var(--aqt-fg-muted)] text-[color:var(--aqt-fg)]"
                    : "border-dashed border-[color:var(--aqt-border)] text-[color:var(--aqt-fg-faint)]"
                )}
              >
                {mapWithModeName(map.map, map.mode) ?? "—"}
                {played ? ` ${mapScore.one}:${mapScore.two}` : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </>
  );

  return href ? (
    <HoverPrefetchLink href={href} className={cardClassName} data-live={live || undefined}>
      {body}
    </HoverPrefetchLink>
  ) : (
    <div className={cardClassName} data-live={live || undefined}>
      {body}
    </div>
  );
}
