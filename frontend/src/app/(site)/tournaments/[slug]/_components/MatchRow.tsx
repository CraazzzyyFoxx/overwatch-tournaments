"use client";

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
  /** Mono leading cell: "21:00 · R5", "M10 · Bo5", a group letter. */
  leading: string;
  /** Mono trailing cell: "Group B · Bo2", "LB Final · Bo3". */
  trailing?: string;
  /** Bracket node for this match; renders a labelled "open in bracket" link when given. */
  bracketHref?: string;
  /** This page's own location, so the pre-game room can send viewers back. */
  returnTo: string;
  className?: string;
};

/**
 * One settled (or scheduled) match as a table-like row. The maps of the series
 * unfold under it via `<details>` — no per-row state — with the log and
 * pre-game links that the bracket node hides behind three unlabeled icons.
 */
export function MatchRow({
  encounter,
  leading,
  trailing,
  bracketHref,
  returnTo,
  className
}: Readonly<MatchRowProps>) {
  const t = useTranslations();
  const completed = isEncounterCompleted(encounter);
  const home = encounter.score?.home ?? 0;
  const away = encounter.score?.away ?? 0;
  const hasScore = completed || home !== 0 || away !== 0;
  const winner: "home" | "away" | null = completed ? (home > away ? "home" : away > home ? "away" : null) : null;
  const maps = encounter.matches ?? [];
  const expandable = maps.length > 0;

  const summary = (
    <div
      className={cn(
        "grid grid-cols-[minmax(5rem,auto)_minmax(0,1fr)_5.5rem_minmax(0,1fr)_auto] items-center gap-2 px-2 py-2.5 text-ui sm:gap-3",
        className
      )}
    >
      <span className="text-label text-[color:var(--aqt-fg-faint)]">{leading}</span>
      <span className={cn("flex min-w-0 justify-end", winner === "home" && "font-semibold", winner === "away" && "text-[color:var(--aqt-fg-dim)]")}>
        <TeamName team={encounter.home_team} fallback={t("common.tbd")} size="sm" reverse />
      </span>
      <span className={cn(styles.score, "text-center")}>
        {hasScore ? (
          <>
            <span className={cn(winner === "home" ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-muted)]")}>{home}</span>
            <span className="mx-1 font-normal text-[color:var(--aqt-fg-faint)]">–</span>
            <span className={cn(winner === "away" ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-muted)]")}>{away}</span>
          </>
        ) : (
          <span className="text-label font-normal uppercase text-[color:var(--aqt-fg-faint)]">vs</span>
        )}
      </span>
      <span className={cn("flex min-w-0", winner === "away" && "font-semibold", winner === "home" && "text-[color:var(--aqt-fg-dim)]")}>
        <TeamName team={encounter.away_team} fallback={t("common.tbd")} size="sm" />
      </span>
      <span className="flex items-center justify-end gap-2 text-label text-[color:var(--aqt-fg-faint)]">
        {trailing ? <span className="hidden sm:inline">{trailing}</span> : null}
        {bracketHref ? (
          <HoverPrefetchLink
            href={bracketHref}
            className="inline-flex hover:text-[color:var(--aqt-teal)]"
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

  if (!expandable) {
    return <div className="border-b border-[color:var(--aqt-border)]/60">{summary}</div>;
  }

  return (
    <details className="group border-b border-[color:var(--aqt-border)]/60">
      <summary className="cursor-pointer list-none [&::-webkit-details-marker]:hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)]">
        {summary}
      </summary>
      <div className="mb-2 ml-2 mr-2 border-l-2 border-[color:var(--aqt-border)] py-1 pl-3 text-caption sm:ml-[6rem]">
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
