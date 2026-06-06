import React from "react";
import { useQuery } from "@tanstack/react-query";

import { Encounter } from "@/types/encounter.types";
import { Standings } from "@/types/tournament.types";
import { cn } from "@/lib/utils";
import { sortStandingsMatches } from "@/lib/tournament-match-order";
import { useTranslation } from "@/i18n/LanguageContext";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { formatTiebreakOrder } from "@/lib/tiebreakers";
import tournamentService from "@/services/tournament.service";

export interface StandingTableProps {
  standings: Standings[];
  is_groups: boolean;
  // Groups: tint the top-N rows and draw a dashed "top N advance" cut-line.
  advanceCount?: number;
  // Playoff/overall: mark rank 1 as the crowned winner.
  crownTop?: boolean;
}

type ResultKind = "w" | "l" | "t";

function resultOf(teamId: number, encounter: Encounter): ResultKind {
  const teamScore =
    encounter.home_team_id === teamId ? encounter.score.home : encounter.score.away;
  const opponentScore =
    encounter.home_team_id === teamId ? encounter.score.away : encounter.score.home;
  if (teamScore === opponentScore) return "t";
  return teamScore > opponentScore ? "w" : "l";
}

function computeMaps(teamId: number, history: Encounter[]) {
  let won = 0;
  let lost = 0;
  for (const encounter of history) {
    const isHome = encounter.home_team_id === teamId;
    won += isHome ? encounter.score.home : encounter.score.away;
    lost += isHome ? encounter.score.away : encounter.score.home;
  }
  return { won, lost, diff: won - lost };
}

function MapDiff({ diff }: { diff: number }) {
  const tone = diff > 0 ? "pos" : diff < 0 ? "neg" : "zero";
  const text = diff > 0 ? `+${diff}` : diff < 0 ? `−${Math.abs(diff)}` : "0";
  return <span className={cn("st-diff", tone)}>{text}</span>;
}

function FormChips({ results }: { results: ResultKind[] }) {
  if (results.length === 0) {
    return <span style={{ color: "var(--fg-faint)" }}>—</span>;
  }
  return (
    <span className="form-chips">
      {results.slice(-5).map((result, index) => (
        <span key={index} className={cn("fc", result)}>
          {result.toUpperCase()}
        </span>
      ))}
    </span>
  );
}

function TeamCell({ standing, showGroup }: { standing: Standings; showGroup: boolean }) {
  const groupName = standing.team?.group?.name;
  return (
    <div className="st-team">
      <div className="stack">
        <span className="nm">{standing.team?.name ?? "—"}</span>
        {showGroup && groupName && <span className="sub">Group {groupName}</span>}
      </div>
    </div>
  );
}

const StandingsTable = ({
  standings,
  is_groups,
  advanceCount = 2,
  crownTop = false,
}: StandingTableProps) => {
  const { t } = useTranslation();

  const tournamentId = standings[0]?.tournament_id;
  const stagesQuery = useQuery({
    queryKey: tournamentQueryKeys.stages(tournamentId),
    queryFn: () => tournamentService.getStages(tournamentId),
    enabled: !!tournamentId,
  });
  const stages = stagesQuery.data ?? [];

  const stage = standings[0]?.stage;
  const settings = stage?.settings_json ?? {};
  let settingsCount =
    typeof settings.advance_count === "number"
      ? settings.advance_count
      : typeof settings.advanceCount === "number"
        ? settings.advanceCount
        : typeof settings.top === "number"
          ? settings.top
          : null;

  if (settingsCount == null && stage != null && stages.length > 0) {
    const currentStage = stages.find((s) => s.id === stage.id);
    const stageItemIds = new Set(currentStage?.items?.map((item) => item.id) ?? []);
    if (stageItemIds.size > 0) {
      let maxPos = 0;
      for (const stg of stages) {
        for (const item of stg.items ?? []) {
          for (const input of item.inputs ?? []) {
            if (
              input.source_stage_item_id != null &&
              stageItemIds.has(input.source_stage_item_id) &&
              input.source_position != null
            ) {
              maxPos = Math.max(maxPos, input.source_position);
            }
          }
        }
      }
      if (maxPos > 0) {
        settingsCount = maxPos;
      }
    }
  }

  const resolvedAdvanceCount = settingsCount ?? advanceCount;

  const sortedStandings = [...standings].sort((a, b) => {
    const left = is_groups ? a.position : a.overall_position;
    const right = is_groups ? b.position : b.overall_position;
    return left - right;
  });

  const showCut = is_groups && sortedStandings.length > resolvedAdvanceCount;
  const columnCount = is_groups ? 9 : 6;

  // "Ranked by …" legend — resolve metric ids through i18n, falling back to the
  // shared English labels when a key is missing.
  const labelFor = (id: string) => {
    const key = `common.tiebreakerMetrics.${id}`;
    const label = t(key);
    return label === key ? undefined : label;
  };
  const tiebreakLegend = is_groups
    ? formatTiebreakOrder(sortedStandings[0]?.tiebreak_order, labelFor)
    : "";

  return (
    <div>
      <div className="st-scroll">
      <table className="st">
        <thead>
          {is_groups ? (
            <tr>
              <th style={{ width: 48 }}>#</th>
              <th>Team</th>
              <th className="c" style={{ width: 80 }}>
                W·D·L
              </th>
              <th className="r" style={{ width: 60 }}>
                Pts
              </th>
              <th className="r" style={{ width: 60 }} title={t("common.headToHead")}>
                H2H
              </th>
              <th className="r" style={{ width: 80 }}>
                {t("common.buchholz")}
              </th>
              <th className="r" style={{ width: 70 }} title={t("common.scoreDiff")}>
                +/−
              </th>
              <th className="c" style={{ width: 120 }}>
                Form
              </th>
              <th className="c" style={{ width: 90 }} />
            </tr>
          ) : (
            <tr>
              <th style={{ width: 56 }}>#</th>
              <th>Team</th>
              <th className="c" style={{ width: 90 }}>
                Record
              </th>
              <th className="r" style={{ width: 170 }}>
                Maps
              </th>
              <th className="r" style={{ width: 80 }}>
                Map Δ
              </th>
              <th className="c" style={{ width: 130 }}>
                Form
              </th>
            </tr>
          )}
        </thead>
        <tbody>
          {sortedStandings.map((standing, index) => {
            const position = is_groups ? standing.position : standing.overall_position;
            const history = sortStandingsMatches(standing.matches_history ?? []);
            const results = history.map((encounter) => resultOf(standing.team_id, encounter));
            const maps = computeMaps(standing.team_id, history);
            const total = maps.won + maps.lost;
            const wPct = total > 0 ? (maps.won / total) * 100 : 0;
            const advancing = is_groups && position <= resolvedAdvanceCount;
            const crowned = !is_groups && crownTop && position === 1;
            const rowClass = crowned ? "crown" : advancing ? "advance" : undefined;

            return (
              <React.Fragment key={`${standing.stage_item_id ?? standing.stage_id ?? "s"}-${standing.team_id}`}>
                <tr className={rowClass}>
                  <td>
                    <span className="st-rank">{position}</span>
                  </td>
                  <td>
                    <TeamCell standing={standing} showGroup={!is_groups} />
                  </td>

                  {is_groups ? (
                    <>
                      <td className="c">
                        <span className="st-record">
                          <span className="w">{standing.win}</span>
                          <span className="sep">·</span>
                          <span className="d">{standing.draw}</span>
                          <span className="sep">·</span>
                          <span className="l">{standing.lose}</span>
                        </span>
                      </td>
                      <td className="r font-mono text-[var(--fg-muted)]">
                        {standing.points.toFixed(1)}
                      </td>
                      <td className="r font-mono text-[var(--fg-dim)]">
                        {standing.tb ? standing.tb : "—"}
                      </td>
                      <td className="r font-mono text-[var(--fg-dim)]">
                        {standing.buchholz != null ? standing.buchholz.toFixed(1) : "—"}
                      </td>
                      <td className="r">
                        <MapDiff diff={standing.score_differential ?? maps.diff} />
                      </td>
                      <td className="c">
                        <FormChips results={results} />
                      </td>
                      <td className="c">
                        {advancing ? (
                          <span className="st-status adv">
                            <span className="arrow" />
                            Adv
                          </span>
                        ) : (
                          <span className="st-status out">Out</span>
                        )}
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="c">
                        <span className="st-record">
                          <span className="w">{standing.win}</span>
                          <span className="sep">·</span>
                          <span className="d">{standing.draw}</span>
                          <span className="sep">·</span>
                          <span className="l">{standing.lose}</span>
                        </span>
                      </td>
                      <td className="r">
                        <span className="st-maps">
                          <span className="num">
                            {maps.won}–{maps.lost}
                          </span>
                          <span className="bar">
                            <span className="w" style={{ width: `${wPct}%` }} />
                            <span className="l" style={{ width: `${100 - wPct}%` }} />
                          </span>
                        </span>
                      </td>
                      <td className="r">
                        <MapDiff diff={maps.diff} />
                      </td>
                      <td className="c">
                        <FormChips results={results} />
                      </td>
                    </>
                  )}
                </tr>

                {showCut && index === resolvedAdvanceCount - 1 && (
                  <tr>
                    <td
                      colSpan={columnCount}
                      className="st-cut"
                      data-label={t("common.topAdvance", { count: resolvedAdvanceCount })}
                    />
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
      </div>
      {tiebreakLegend ? (
        <p className="mt-2 px-1 text-xs text-[var(--fg-faint)]">
          {t("common.tiebreakers")}: {tiebreakLegend}
        </p>
      ) : null}
    </div>
  );
};

export default StandingsTable;
