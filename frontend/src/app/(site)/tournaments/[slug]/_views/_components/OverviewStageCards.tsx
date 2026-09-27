"use client";

import { useTranslations } from "next-intl";

import TeamName from "@/components/TeamName";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import type { BracketRoundShape } from "@/lib/bracket/round-name";
import type { RoundGroup } from "@/lib/bracket/view";
import { cn } from "@/lib/utils";
import type { Encounter } from "@/types/encounter.types";
import type { StageSummary, Standings } from "@/types/tournament.types";

import { MatchCard } from "../../_components/MatchCard";
import { currentRoundOf, pickRoundWindow, splitStandingsByGroup } from "../tournamentOverview.model";
import type { OverviewMatchPresenter } from "../useOverviewMatchPresenter";
import { CardLink, OverviewCard } from "./OverviewCards";

/**
 * The mini bracket (§3 ⑥): a window of rounds around the one being played,
 * ending on the stage's decider. The caller decides whether the stage has a
 * bracket to draw at all — a group stage gets `OverviewGroupTable` instead.
 */
export function OverviewMiniBracket({
  stage,
  roundGroups,
  stageEncounters,
  roundShape,
  overviewHref,
  presenter
}: Readonly<{
  stage: StageSummary;
  roundGroups: readonly RoundGroup[];
  stageEncounters: readonly Encounter[];
  roundShape: BracketRoundShape;
  overviewHref: string;
  presenter: OverviewMatchPresenter;
}>) {
  const t = useTranslations();
  const roundLabel = useBracketRoundLabel();

  return (
    <OverviewCard
      title={t("tournamentDetail.overview.bracketMini.title", { stage: stage.name })}
      action={
        <CardLink href={`${overviewHref}/bracket?stage=${stage.id}`}>
          {t("tournamentDetail.overview.bracketMini.open")}
        </CardLink>
      }
    >
      <div className="flex gap-2 overflow-x-auto pb-1">
        {pickRoundWindow(roundGroups, currentRoundOf(roundGroups)).map((group) => (
          <div className="min-w-[13rem] flex-1 space-y-1.5" key={group.round}>
            <div className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
              {roundLabel(group.round, roundShape)}
            </div>
            {group.matches.map((match) => {
              const encounter = stageEncounters.find((item) => item.id === match.id);
              if (!encounter) return null;
              return (
                <MatchCard
                  key={encounter.id}
                  encounter={encounter}
                  eyebrow={presenter.eyebrowOf(encounter)}
                  href={presenter.bracketHref(encounter)}
                  size="sm"
                  streamsCount={presenter.streamsCountOf(encounter)}
                />
              );
            })}
          </div>
        ))}
      </div>
    </OverviewCard>
  );
}

/** The group stage's ladders, in place of a bracket the stage does not have. */
export function OverviewGroupTable({
  stage,
  stageStandings,
  overviewHref
}: Readonly<{
  stage: StageSummary;
  stageStandings: readonly Standings[];
  overviewHref: string;
}>) {
  const t = useTranslations();

  const standingsGroups = splitStandingsByGroup(stageStandings);
  // One decimal everywhere as soon as any row carries a half point: a
  // right-aligned column of "4" beside "3.5" has no shared decimal to scan.
  const pointsHaveFraction = stageStandings.some((row) => !Number.isInteger(row.points));
  const formatPoints = (points: number) =>
    pointsHaveFraction ? points.toFixed(1) : String(points);

  return (
    <OverviewCard
      title={t("tournamentDetail.overview.groupTable.title", { stage: stage.name })}
      action={
        <CardLink href={`${overviewHref}/bracket?stage=${stage.id}&view=standings`}>
          {t("tournamentDetail.overview.groupTable.open")}
        </CardLink>
      }
    >
      {/* Two groups sit side by side rather than stacking: it halves the card
          and pulls the record back next to the name instead of stranding it
          against the far edge of a 900px row. */}
      <div className={cn("grid gap-x-8 gap-y-5", standingsGroups.length > 1 && "sm:grid-cols-2")}>
        {standingsGroups.map((group) => (
          <table className="w-full table-fixed text-sm" key={group.key}>
            <caption
              className={cn(
                "text-left",
                group.name === null
                  ? "sr-only"
                  : "pb-1.5 text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]"
              )}
            >
              {group.name === null
                ? t("tournamentDetail.overview.groupTable.title", { stage: stage.name })
                : `${t("common.group")} ${group.name}`}
            </caption>
            <thead>
              <tr className="border-b border-[color:var(--aqt-border)] text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                <th scope="col" className="w-8 py-1.5 pr-2 text-left font-medium">
                  <span aria-hidden>{t("tournamentDetail.overview.groupTable.pos")}</span>
                  <span className="sr-only">
                    {t("tournamentDetail.overview.groupTable.posLabel")}
                  </span>
                </th>
                <th scope="col" className="py-1.5 pr-2 text-left font-medium">
                  {t("tournamentDetail.overview.groupTable.team")}
                </th>
                <th scope="col" className="w-20 py-1.5 pr-2 text-right font-medium">
                  {t("standings.colWDL")}
                </th>
                <th scope="col" className="w-12 py-1.5 text-right font-medium">
                  {t("tournamentDetail.overview.groupTable.points")}
                </th>
              </tr>
            </thead>
            <tbody>
              {group.rows.map((row) => (
                <tr key={row.id}>
                  <td className="aqt-tnum py-1.5 pr-2 text-[color:var(--aqt-fg-muted)]">
                    {row.position}
                  </td>
                  <td className="py-1.5 pr-2">
                    <TeamName team={row.team ?? { name: t("common.tbd") }} size="xs" />
                  </td>
                  {/* W·D·L, not W–L: these stages draw, and a "3–0" printed
                      for a 3W-2D-0L run contradicts both the matches played
                      and the points beside it. */}
                  <td className="aqt-tnum py-1.5 pr-2 text-right">
                    {row.win}·{row.draw}·{row.lose}
                  </td>
                  <td className="aqt-tnum py-1.5 text-right font-semibold">
                    {formatPoints(row.points)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
      </div>
    </OverviewCard>
  );
}
