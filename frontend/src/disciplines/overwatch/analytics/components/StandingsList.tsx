"use client";

import React, { useMemo } from "react";
import { ChevronRight } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import TeamName from "@/components/TeamName";
import { TeamPlacement } from "@/components/TournamentTeamCard";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { RowButton } from "@/components/ui/row-button";
import { Separator } from "@/components/ui/separator";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { groupDisplayName, groupHue } from "@/lib/tournament/group";
import { formatPlace, standingsRank } from "@/disciplines/overwatch/analytics/analytics.helpers";
import type { TeamVM } from "@/disciplines/overwatch/analytics/useAnalyticsViewModel";

import { AnomalyKinds } from "./AnomalyFlag";
import DeltaText, { moveTone } from "./DeltaText";

export type StandingsMode = "standings" | "movers" | "watch";

interface StandingsListProps {
  teams: TeamVM[];
  selectedTeamId: number | null;
  onSelectTeam: (teamId: number) => void;
  mode: StandingsMode;
  onModeChange: (mode: StandingsMode) => void;
  /** The tournament has ended: places 1–3 are medals. */
  ended: boolean;
  /** The teams span several groups, so the group colour tells them apart. */
  showGroups: boolean;
  /** Trailing control on the toolbar row (the list/table view toggle). */
  headerEnd?: React.ReactNode;
}

function sortTeams(teams: TeamVM[], mode: StandingsMode): TeamVM[] {
  if (mode === "movers") {
    return [...teams].sort((a, b) => Math.abs(b.placement_delta ?? 0) - Math.abs(a.placement_delta ?? 0));
  }
  if (mode === "watch") return teams.filter((team) => team.flagCount > 0);
  return [...teams].sort((a, b) => standingsRank(a) - standingsRank(b));
}

/**
 * Predicted → actual on the bracket's place scale: the hollow dot is the
 * forecast, the filled one the finish, the segment between them coloured by
 * direction. One summary sentence names it for assistive tech and in `title`;
 * before the bracket is played only the forecast is drawn.
 */
function PlaceConnector({ team, maxPosition }: Readonly<{ team: TeamVM; maxPosition: number }>) {
  const t = useTranslations();
  const locale = useLocale() as "en" | "ru";
  const predicted = team.predicted_place;
  if (predicted == null || maxPosition < 2) return <span aria-hidden />;

  const actual = team.placement;
  const pos = (place: number) => `${((place - 1) / (maxPosition - 1)) * 100}%`;
  const predictedText = t("analytics.community.team.predictedShort", { place: formatPlace(predicted, locale) });
  const summary =
    actual == null
      ? predictedText
      : `${predictedText}, ${t("analytics.community.team.finishedShort", { place: formatPlace(actual, locale) })}`;
  const color = moveTone(team.placement_delta);

  return (
    <span role="img" aria-label={summary} title={summary} className="relative block h-4 min-w-0">
      <Separator className="absolute inset-x-0 top-1/2 -translate-y-1/2 bg-[color:var(--aqt-border-2)]" />
      {actual != null && actual !== predicted ? (
        <span
          className="absolute top-1/2 h-0.5 -translate-y-1/2 rounded-full"
          style={{
            left: pos(Math.min(predicted, actual)),
            right: `calc(100% - ${pos(Math.max(predicted, actual))})`,
            background: color
          }}
        />
      ) : null}
      <span
        className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[color:var(--aqt-fg-dim)] bg-[color:var(--aqt-card)]"
        style={{ left: pos(predicted) }}
      />
      {actual != null ? (
        <span
          className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full"
          style={{ left: pos(actual), background: actual === predicted ? "var(--aqt-fg-dim)" : color }}
        />
      ) : null}
    </span>
  );
}

/**
 * The standings: Standings / Biggest movers / Watch list over one framed list
 * whose rows carry the place, the team, its record and flags, the
 * predicted → actual connector and the place delta; a row selects its team for
 * the detail panel.
 */
export default function StandingsList({
  teams,
  selectedTeamId,
  onSelectTeam,
  mode,
  onModeChange,
  ended,
  showGroups,
  headerEnd
}: Readonly<StandingsListProps>) {
  const t = useTranslations();
  const locale = useLocale() as "en" | "ru";
  const hasFlags = teams.some((team) => team.flagCount > 0);
  // The watch list is only a choice while something is flagged (DESIGN.md §0.3).
  const activeMode: StandingsMode = mode === "watch" && !hasFlags ? "standings" : mode;
  const rows = useMemo(() => sortTeams(teams, activeMode), [teams, activeMode]);
  const maxPosition = useMemo(
    () => teams.reduce((max, team) => Math.max(max, team.placement ?? 0, team.predicted_place ?? 0), 0),
    [teams]
  );

  const modes: { value: StandingsMode; label: string }[] = [
    { value: "standings", label: t("analytics.community.standings.sortStandings") },
    { value: "movers", label: t("analytics.community.standings.sortMovers") },
    ...(hasFlags ? [{ value: "watch" as const, label: t("analytics.community.standings.sortWatch") }] : [])
  ];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ToggleGroup
          variant="pill"
          size="sm"
          value={activeMode}
          onValueChange={(next) => next && onModeChange(next as StandingsMode)}
          aria-label={t("analytics.community.standings.sortLabel")}
        >
          {modes.map((option) => (
            <ToggleGroupItem key={option.value} value={option.value}>
              {option.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {headerEnd}
      </div>

      <Card className="overflow-hidden">
        <ul className="divide-y divide-[color:var(--aqt-border)]">
          {rows.map((team) => (
            <li key={team.id}>
              <RowButton
                aria-current={selectedTeamId === team.id ? "true" : undefined}
                onClick={() => onSelectTeam(team.id)}
                className="grid grid-cols-[2.25rem_minmax(0,1fr)_auto_1rem] items-center gap-x-3 px-3.5 py-2.5 sm:grid-cols-[2.25rem_minmax(0,1.5fr)_minmax(5rem,1fr)_3.75rem_1rem] sm:gap-x-4"
              >
                <span className="flex justify-center">
                  {team.placement != null ? (
                    <TeamPlacement placement={team.placement} medal={ended} />
                  ) : team.predicted_place != null ? (
                    <span
                      className="aqt-tnum text-caption text-[color:var(--aqt-fg-dim)]"
                      title={t("analytics.community.team.predictedShort", {
                        place: formatPlace(team.predicted_place, locale)
                      })}
                    >
                      #{team.predicted_place}
                    </span>
                  ) : null}
                </span>
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="flex min-w-0 items-center gap-2">
                    <TeamName team={team} size="sm" nameClassName="text-ui font-semibold text-[color:var(--aqt-fg)]" />
                    {showGroups && team.group?.name ? (
                      <Badge
                        hue={groupHue(team.group.name)}
                        voice="label"
                        className="hidden shrink-0 sm:inline-flex"
                      >
                        {groupDisplayName(team.group.name, t("common.group"))}
                      </Badge>
                    ) : null}
                  </span>
                  <span className="flex min-w-0 items-center gap-1.5 text-caption text-[color:var(--aqt-fg-muted)]">
                    <span className="aqt-tnum">
                      {team.wins}–{team.losses}
                    </span>
                    {team.anomalies.length > 0 ? (
                      <>
                        <span className="text-[color:var(--aqt-fg-dim)]">·</span>
                        <AnomalyKinds anomalies={team.anomalies} />
                      </>
                    ) : null}
                  </span>
                </span>
                {/* Capped: on a wide list the scale stays readable instead of stretching across it. */}
                <span className="hidden w-full max-w-[13rem] justify-self-end sm:block">
                  <PlaceConnector team={team} maxPosition={maxPosition} />
                </span>
                <span className="flex justify-end">
                  <DeltaText delta={team.placement_delta} />
                </span>
                <ChevronRight aria-hidden className="size-4 text-[color:var(--aqt-fg-faint)]" />
              </RowButton>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
