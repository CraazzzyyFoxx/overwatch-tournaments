"use client";

import type { ReactNode } from "react";
import { ArrowUpRight, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import TeamName from "@/components/TeamName";
import { disclosureChevronClass } from "@/components/ui/chevron";
import Image from "@/components/ui/image";
import { withReturnTo } from "@/lib/auth/return-to";
import { encounterSeatScore } from "@/lib/encounter/detail";
import { seatAt, seatTeam } from "@/lib/encounter/seats";
import { getEncounterWinner, isEncounterCompleted } from "@/lib/encounter/status";
import { cn } from "@/lib/utils";
import type { Encounter } from "@/types/encounter.types";

/**
 * One grid for the series line and every map line under it, every track but the two team tracks a fixed width — so
 * the team tracks come out equal in each line and a map's score sits exactly under the series score: the left number
 * is always the left team's. Under 640px: team · score · team · chevron; from 640px the lead and the actions join.
 */
const LINE =
  "grid grid-cols-[minmax(0,1fr)_1.25rem_0.75rem_1.25rem_minmax(0,1fr)_1rem] items-center gap-x-2 px-3.5 sm:grid-cols-[6rem_minmax(0,1fr)_1.75rem_1rem_1.75rem_minmax(0,1fr)_3.25rem] sm:gap-x-3";
const ROW_HOVER = "transition-colors hover:bg-[color:var(--aqt-overlay-2)]";
const LINK = "text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-teal)]";

const clock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;

export type MatchRowProps = {
  encounter: Encounter;
  /** Leading cell: "21:00", "M10", a group chip. */
  leading?: ReactNode;
  /** Trailing cell: "Group B · Bo2", "LB Final · Bo3". */
  trailing?: string;
  /** Bracket node for this match; renders a labelled "open in bracket" link when given. */
  bracketHref?: string;
  /** This page's own location, so the pre-game room can send viewers back. */
  returnTo: string;
};

/**
 * One match as a row, its maps unfolding under it via `<details>` (no per-row state). The maps read like the
 * scoreboard above them: each map's score under the series score, its winner's number in teal, the map's stats link
 * only when it has a log, and the pre-game room only while there is a game ahead. A match with no maps has nothing to
 * unfold, so the whole row opens the match page. Under 640px the series is one line.
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
  const winner = getEncounterWinner(encounter);
  const one = seatAt(encounter.teams, 1);
  const two = seatAt(encounter.teams, 2);
  const hasScore = completed || (one?.score ?? 0) !== 0 || (two?.score ?? 0) !== 0;
  const maps = [...(encounter.matches ?? [])].sort(
    (a, b) => (a.map_index ?? 0) - (b.map_index ?? 0)
  );
  const won = "font-semibold text-[color:var(--aqt-fg)]";
  const lost = winner === null ? undefined : "text-[color:var(--aqt-fg-dim)]";
  const score = (value: number, lead: boolean) => (
    <span
      className={cn(
        "aqt-tnum text-center font-display text-ui font-bold sm:text-title sm:leading-none",
        lead ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-muted)]",
        !hasScore && "text-[color:var(--aqt-fg-faint)]"
      )}
    >
      {hasScore ? value : "–"}
    </span>
  );

  const summary = (
    <div className={cn(LINE, "relative py-2.5 text-ui")}>
      {maps.length === 0 ? (
        <HoverPrefetchLink
          href={`/encounters/${encounter.id}`}
          className="absolute inset-0 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)]"
          aria-label={t("bracket.viewMatch")}
        />
      ) : null}
      <span className="min-w-0 truncate text-label text-[color:var(--aqt-fg-faint)] max-sm:hidden">
        {leading}
      </span>
      <TeamName
        team={seatTeam(one)}
        fallback={t("common.tbd")}
        size="sm"
        reverse
        className={cn("justify-self-end", winner === 1 ? won : lost)}
      />
      {score(one?.score ?? 0, winner === 1)}
      <span className="text-center text-[color:var(--aqt-fg-faint)]">
        {hasScore ? "–" : <span className="text-label uppercase">vs</span>}
      </span>
      {score(two?.score ?? 0, winner === 2)}
      <TeamName
        team={seatTeam(two)}
        fallback={t("common.tbd")}
        size="sm"
        className={winner === 2 ? won : lost}
      />
      <span className="flex items-center justify-end gap-2 text-label text-[color:var(--aqt-fg-faint)]">
        {trailing ? <span className="hidden whitespace-nowrap xl:inline">{trailing}</span> : null}
        {bracketHref ? (
          <HoverPrefetchLink
            href={bracketHref}
            className="relative hidden hover:text-[color:var(--aqt-teal)] sm:inline-flex"
            aria-label={t("tournamentDetail.matchRow.openInBracket")}
            title={t("tournamentDetail.matchRow.openInBracket")}
          >
            <ArrowUpRight className="size-3.5" aria-hidden />
          </HoverPrefetchLink>
        ) : null}
        {maps.length > 0 ? (
          <ChevronDown className={cn(disclosureChevronClass, "size-3.5")} aria-hidden />
        ) : null}
      </span>
    </div>
  );

  const border = "border-b border-[color:var(--aqt-border)]/60 last:border-b-0";
  if (maps.length === 0) return <div className={cn(border, ROW_HOVER)}>{summary}</div>;

  return (
    <details className={cn("group/disclosure", border)}>
      <summary
        className={cn(
          "cursor-pointer list-none [&::-webkit-details-marker]:hidden focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)]",
          ROW_HOVER
        )}
      >
        {summary}
      </summary>
      <div className="bg-[color:var(--aqt-overlay-1)] pb-2 text-caption">
        {maps.map((map, index) => {
          const mapScore = encounterSeatScore(map, encounter);
          const mapWinner =
            mapScore && mapScore.one !== mapScore.two
              ? mapScore.one > mapScore.two
                ? 1
                : 2
              : null;
          const mode = map.mode ?? map.map?.parent ?? null;
          return (
            <div key={map.id} className={cn(LINE, "py-1.5")}>
              <span className="truncate text-label tracking-wide text-[color:var(--aqt-fg-faint)] uppercase max-sm:hidden">
                {t("tournamentDetail.matchRow.map", { n: map.map_index ?? index + 1 })}
              </span>
              <span className="flex min-w-0 items-center gap-2">
                {mode?.image_path ? (
                  <Image
                    src={mode.image_path}
                    alt=""
                    width={13}
                    height={13}
                    aria-hidden
                    className="shrink-0 opacity-70"
                  />
                ) : null}
                <span className="truncate font-semibold">{map.map?.name ?? "—"}</span>
                {mode ? (
                  <span className="truncate text-[color:var(--aqt-fg-dim)] max-md:hidden">
                    {mode.name}
                  </span>
                ) : null}
              </span>
              {mapScore ? (
                <>
                  <span
                    className={cn(
                      "aqt-tnum text-center font-semibold",
                      mapWinner === 1
                        ? "text-[color:var(--aqt-teal)]"
                        : "text-[color:var(--aqt-fg-muted)]"
                    )}
                  >
                    {mapScore.one}
                  </span>
                  <span className="text-center text-[color:var(--aqt-fg-faint)]">–</span>
                  <span
                    className={cn(
                      "aqt-tnum text-center font-semibold",
                      mapWinner === 2
                        ? "text-[color:var(--aqt-teal)]"
                        : "text-[color:var(--aqt-fg-muted)]"
                    )}
                  >
                    {mapScore.two}
                  </span>
                </>
              ) : (
                <span className="col-span-3 text-center text-[color:var(--aqt-fg-faint)]">—</span>
              )}
              <span className="flex min-w-0 items-center justify-end gap-3 text-label">
                <span className="aqt-tnum text-[color:var(--aqt-fg-dim)]">
                  {map.duration_s != null ? clock(map.duration_s) : "—"}
                </span>
                {map.log_name ? (
                  <HoverPrefetchLink
                    href={`/matches/${map.id}`}
                    className={cn(LINK, "max-sm:hidden")}
                  >
                    {t("tournamentDetail.matchRow.mapStats")}
                  </HoverPrefetchLink>
                ) : null}
              </span>
              <span className="flex justify-end">
                {map.log_name ? (
                  <HoverPrefetchLink
                    href={`/matches/${map.id}`}
                    className={cn(LINK, "sm:hidden")}
                    aria-label={t("tournamentDetail.matchRow.mapStats")}
                  >
                    <ArrowUpRight className="size-3.5" aria-hidden />
                  </HoverPrefetchLink>
                ) : null}
              </span>
            </div>
          );
        })}
        {/* On the same grid, so the links start where the map names do. */}
        <div className={cn(LINE, "mt-1 pt-1.5 text-label")}>
          <span className="max-sm:hidden" />
          <span className="col-span-5 flex gap-4 max-sm:col-span-6">
            <HoverPrefetchLink href={`/encounters/${encounter.id}`} className={LINK}>
              {t("tournamentDetail.matchRow.matchPage")}
            </HoverPrefetchLink>
            {completed ? null : (
              <HoverPrefetchLink
                href={withReturnTo(
                  `/tournaments/${encounter.tournament_id}/pregame/${encounter.id}`,
                  returnTo
                )}
                className={LINK}
              >
                {t("bracket.pregameRoom")}
              </HoverPrefetchLink>
            )}
          </span>
        </div>
      </div>
    </details>
  );
}
