"use client";

import type { ReactNode } from "react";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { ArrowUpRight, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import TeamName from "@/components/TeamName";
import { Eyebrow } from "@/components/ui/eyebrow";
import { withReturnTo } from "@/lib/auth/return-to";
import { encounterSeatScore } from "@/lib/encounter/detail";
import { getEncounterWinner, isEncounterCompleted } from "@/lib/encounter/status";
import { seatAt, seatTeam, type DuelSlot } from "@/lib/encounter/seats";
import { cn } from "@/lib/utils";
import type { Encounter, Match } from "@/types/encounter.types";

export type MatchRowProps = {
  encounter: Encounter;
  /** Leading cell: "21:00", "M10", a group chip. */
  leading?: ReactNode;
  /** Mono trailing cell: "Group B · Bo2", "LB Final · Bo3". */
  trailing?: string;
  /** Bracket node for this match; renders a labelled "open in bracket" link when given. */
  bracketHref?: string;
  /** This page's own location, so the pre-game room can send viewers back. */
  returnTo: string;
};

const ROW_HOVER = "transition-colors hover:bg-[color:var(--aqt-overlay-2)]";

/** A score: the display face, heavier and larger than the team names beside it. */
const SCORE = "font-display text-title leading-none font-bold tabular-nums";

/**
 * Each cell's place in the row, by grid line so the DOM stays one. Under 640px
 * the row is the bracket node — lead and actions on top, each team on its own
 * line with its score on the right, so neither name is cut to fit the other.
 * From 640px it is the scoreboard line: lead · slot 1 · score – score · slot 2
 * · actions, the names leaning on the score.
 */
const CELL = {
  lead: "col-span-2 col-start-1 row-start-1 sm:col-span-1 sm:col-start-1",
  t1: "col-start-1 row-start-2 sm:col-start-2 sm:row-start-1 sm:justify-self-end",
  s1: "col-span-2 col-start-2 row-start-2 justify-self-end sm:col-span-1 sm:col-start-3 sm:row-start-1",
  dash: "hidden sm:col-start-4 sm:row-start-1 sm:block",
  s2: "col-span-2 col-start-2 row-start-3 justify-self-end sm:col-span-1 sm:col-start-5 sm:row-start-1 sm:justify-self-start",
  t2: "col-start-1 row-start-3 sm:col-start-6 sm:row-start-1",
  act: "col-start-3 row-start-1 sm:col-start-7"
} as const;

/**
 * One settled (or scheduled) match as a row. The maps of the series unfold
 * under it via `<details>` — no per-row state — with the log and pre-game
 * links that the bracket node hides behind three unlabeled icons. A match with
 * no maps has nothing to unfold, so the whole row opens the match page.
 */
export function MatchRow({
  encounter,
  leading,
  trailing,
  bracketHref,
  returnTo
}: Readonly<MatchRowProps>) {
  const t = useTranslations();
  const completed = isEncounterCompleted(encounter);
  const seatScoreLabel = (map: Match) => {
    const score = encounterSeatScore(map, encounter);
    return score ? `${score.one} : ${score.two}` : "—";
  };
  const scoreOne = seatAt(encounter.teams, 1)?.score ?? 0;
  const scoreTwo = seatAt(encounter.teams, 2)?.score ?? 0;
  const hasScore = completed || scoreOne !== 0 || scoreTwo !== 0;
  const winner = getEncounterWinner(encounter);
  const maps = encounter.matches ?? [];
  const expandable = maps.length > 0;

  const side = (slot: DuelSlot) => {
    const won = winner === slot;
    const lost = winner !== null && !won;
    const team = seatTeam(seatAt(encounter.teams, slot));
    return (
      <span
        data-cell={`t${slot}`}
        className={cn(
          "flex min-w-0",
          CELL[`t${slot}`],
          won && "font-semibold text-[color:var(--aqt-fg)]",
          lost && "text-[color:var(--aqt-fg-dim)]"
        )}
      >
        <TeamName
          team={team}
          fallback={t("common.tbd")}
          size="sm"
          // Slot 1's name leans on the score from the left on the scoreboard
          // line; stacked under 640px both names read from the left edge.
          className={slot === 1 ? "sm:flex-row-reverse" : undefined}
        />
      </span>
    );
  };

  const score = (slot: DuelSlot) => (
    <span
      data-cell={`s${slot}`}
      className={cn(
        SCORE,
        CELL[`s${slot}`],
        winner === slot ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-muted)]",
        !hasScore && "text-[color:var(--aqt-fg-faint)] sm:invisible"
      )}
    >
      {hasScore ? (slot === 1 ? scoreOne : scoreTwo) : "–"}
    </span>
  );

  const summary = (
    <div
      data-match-row
      className="relative grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-x-3 gap-y-1 px-3.5 py-2.5 text-ui sm:grid-cols-[minmax(4.5rem,auto)_minmax(0,1fr)_1.5rem_auto_1.5rem_minmax(0,1fr)_auto] sm:gap-y-0"
    >
      {/* The stretched link sits under the cells; the bracket link is lifted
          above it, so the two never nest. */}
      {expandable ? null : (
        <HoverPrefetchLink
          href={`/encounters/${encounter.id}`}
          className="absolute inset-0 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)]"
          aria-label={t("bracket.viewMatch")}
        />
      )}
      <span data-cell="lead" className={cn("min-w-0 text-label text-[color:var(--aqt-fg-faint)]", CELL.lead)}>
        {leading}
      </span>
      {side(1)}
      {score(1)}
      <span data-cell="dash" className={cn(SCORE, CELL.dash, "text-center font-normal text-[color:var(--aqt-fg-faint)]")}>
        {hasScore ? "–" : <span className="text-label uppercase">vs</span>}
      </span>
      {score(2)}
      {side(2)}
      <span
        data-cell="act"
        className={cn("flex items-center justify-end gap-2 text-label text-[color:var(--aqt-fg-faint)]", CELL.act)}
      >
        {trailing ? <span className="hidden whitespace-nowrap sm:inline">{trailing}</span> : null}
        {bracketHref ? (
          <HoverPrefetchLink
            href={bracketHref}
            /* Negative margin, not a bigger row: the touch target reaches 40px
               while the row keeps its density. */
            className="relative -m-2 inline-flex p-2 hover:text-[color:var(--aqt-teal)] md:m-0 md:p-0"
            aria-label={t("tournamentDetail.matchRow.openInBracket")}
            title={t("tournamentDetail.matchRow.openInBracket")}
          >
            <ArrowUpRight className="size-3.5" aria-hidden />
          </HoverPrefetchLink>
        ) : null}
        {expandable ? (
          <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" aria-hidden />
        ) : (
          <span className="inline-block size-3.5" aria-hidden />
        )}
      </span>
    </div>
  );

  const rowBorder = "border-b border-[color:var(--aqt-border)]/60 last:border-b-0";

  if (!expandable) {
    return <div className={cn(rowBorder, ROW_HOVER)}>{summary}</div>;
  }

  return (
    <details className={cn("group", rowBorder)}>
      <summary
        className={cn(
          "cursor-pointer list-none [&::-webkit-details-marker]:hidden focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)]",
          ROW_HOVER
        )}
      >
        {summary}
      </summary>
      <div className="mx-3.5 mb-2 border-l-2 border-[color:var(--aqt-border)] py-1 pl-3 text-caption sm:ml-[6rem]">
        <Eyebrow as="div" className="grid grid-cols-[minmax(8rem,14rem)_minmax(0,1fr)_4rem_4rem_auto] gap-2 py-0.5">
          <span>{t("tournamentDetail.matchRow.map")}</span>
          <span>{t("tournamentDetail.matchRow.mode")}</span>
          <span className="text-right">{t("tournamentDetail.matchRow.score")}</span>
          <span className="text-right">{t("tournamentDetail.matchRow.duration")}</span>
          <span />
        </Eyebrow>
        {maps.map((map) => (
          <div
            key={map.id}
            className="grid grid-cols-[minmax(8rem,14rem)_minmax(0,1fr)_4rem_4rem_auto] items-center gap-2 py-1"
          >
            <span className="truncate font-semibold">{map.map?.name ?? "—"}</span>
            <span className="truncate text-[color:var(--aqt-fg-muted)]">{(map.mode ?? map.map?.parent)?.name ?? "—"}</span>
            <span className="text-right tabular-nums">
              {seatScoreLabel(map)}
            </span>
            <span className="text-right tabular-nums">
              {map.duration_s != null
                ? `${Math.floor(map.duration_s / 60)}:${String(Math.round(map.duration_s % 60)).padStart(2, "0")}`
                : "—"}
            </span>
            <span className="flex justify-end gap-2 text-label">
              {map.log_name ? (
                <HoverPrefetchLink href={`/matches/${map.id}`} className="text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-teal)]">
                  {t("tournamentDetail.matchRow.log")}
                </HoverPrefetchLink>
              ) : null}
            </span>
          </div>
        ))}
        <div className="mt-1.5 flex gap-3 border-t border-[color:var(--aqt-border)]/60 pt-1.5 text-label">
          <HoverPrefetchLink href={`/encounters/${encounter.id}`} className="text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-teal)]">
            {t("bracket.viewMatch")}
          </HoverPrefetchLink>
          <HoverPrefetchLink
            href={withReturnTo(`/tournaments/${encounter.tournament_id}/pregame/${encounter.id}`, returnTo)}
            className="text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-teal)]"
          >
            {t("bracket.pregameRoom")}
          </HoverPrefetchLink>
        </div>
      </div>
    </details>
  );
}
