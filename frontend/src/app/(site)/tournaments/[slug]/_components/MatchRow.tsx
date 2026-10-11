"use client";

import type { ReactNode } from "react";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { ArrowUpRight, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import TeamName from "@/components/TeamName";
import { withReturnTo } from "@/lib/auth/return-to";
import { isEncounterCompleted } from "@/lib/encounter/status";
import { cn } from "@/lib/utils";
import type { Encounter } from "@/types/encounter.types";

import styles from "../TournamentDetail.module.css";

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
  const home = encounter.score?.home ?? 0;
  const away = encounter.score?.away ?? 0;
  const hasScore = completed || home !== 0 || away !== 0;
  const winner: "home" | "away" | null = completed ? (home > away ? "home" : away > home ? "away" : null) : null;
  const maps = encounter.matches ?? [];
  const expandable = maps.length > 0;

  const side = (which: "home" | "away") => {
    const won = winner === which;
    const lost = winner !== null && !won;
    const team = which === "home" ? encounter.home_team : encounter.away_team;
    return (
      <span
        data-cell={which}
        className={cn(
          "flex min-w-0",
          won && "font-semibold text-[color:var(--aqt-fg)]",
          lost && "text-[color:var(--aqt-fg-dim)]"
        )}
      >
        <TeamName
          team={team}
          fallback={t("common.tbd")}
          size="sm"
          // The home name leans on the score from the left on the scoreboard
          // line; stacked under 640px both names read from the left edge.
          className={which === "home" ? "sm:flex-row-reverse" : undefined}
        />
      </span>
    );
  };

  const score = (which: "home" | "away") => (
    <span
      data-cell={which === "home" ? "hs" : "as"}
      className={cn(
        styles.score,
        winner === which ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-muted)]",
        !hasScore && "text-[color:var(--aqt-fg-faint)] sm:invisible"
      )}
    >
      {hasScore ? (which === "home" ? home : away) : "–"}
    </span>
  );

  const summary = (
    <div data-match-row className={cn(styles.matchRow, "relative px-3.5 py-2.5 text-ui")}>
      {/* The stretched link sits under the cells; the bracket link is lifted
          above it, so the two never nest. */}
      {expandable ? null : (
        <HoverPrefetchLink
          href={`/encounters/${encounter.id}`}
          className="absolute inset-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)]"
          aria-label={t("bracket.viewMatch")}
        />
      )}
      <span data-cell="lead" className="min-w-0 text-label text-[color:var(--aqt-fg-faint)]">
        {leading}
      </span>
      {side("home")}
      {score("home")}
      <span data-cell="dash" className={cn(styles.score, "text-center font-normal text-[color:var(--aqt-fg-faint)]")}>
        {hasScore ? "–" : <span className="text-label uppercase">vs</span>}
      </span>
      {score("away")}
      {side("away")}
      <span data-cell="act" className="flex items-center justify-end gap-2 text-label text-[color:var(--aqt-fg-faint)]">
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
          "cursor-pointer list-none [&::-webkit-details-marker]:hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)]",
          ROW_HOVER
        )}
      >
        {summary}
      </summary>
      <div className="mx-3.5 mb-2 border-l-2 border-[color:var(--aqt-border)] py-1 pl-3 text-caption sm:ml-[6rem]">
        <div className="grid grid-cols-[minmax(8rem,14rem)_minmax(0,1fr)_4rem_4rem_auto] gap-2 py-0.5 text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
          <span>{t("tournamentDetail.matchRow.map")}</span>
          <span>{t("tournamentDetail.matchRow.mode")}</span>
          <span className="text-right">{t("tournamentDetail.matchRow.score")}</span>
          <span className="text-right">{t("tournamentDetail.matchRow.duration")}</span>
          <span />
        </div>
        {maps.map((map) => (
          <div
            key={map.id}
            className="grid grid-cols-[minmax(8rem,14rem)_minmax(0,1fr)_4rem_4rem_auto] items-center gap-2 py-1"
          >
            <span className="truncate font-semibold">{map.map?.name ?? "—"}</span>
            <span className="truncate text-[color:var(--aqt-fg-muted)]">{map.map?.gamemode?.name ?? "—"}</span>
            <span className="text-right tabular-nums">
              {map.score ? `${map.score.home} : ${map.score.away}` : "—"}
            </span>
            <span className="text-right tabular-nums">
              {map.time != null
                ? `${Math.floor(map.time / 60)}:${String(Math.round(map.time % 60)).padStart(2, "0")}`
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
