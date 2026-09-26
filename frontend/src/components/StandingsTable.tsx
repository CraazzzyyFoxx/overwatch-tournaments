import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Lock } from "lucide-react";

import { Encounter } from "@/types/encounter.types";
import { Stage, Standings } from "@/types/tournament.types";
import { cn } from "@/lib/utils";
import { sortStandingsMatches } from "@/lib/tournament/match-order";
import { straddlingTieGroups } from "@/lib/tournament/tie-clusters";
import { useTranslations } from "next-intl";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { tiebreakerLabel, type TiebreakerMetricId } from "@/lib/tournament/tiebreakers";
import tournamentService from "@/services/tournament.service";
import styles from "./StandingsTable.module.css";
import TeamName from "@/components/TeamName";

interface StandingTableProps {
  standings: Standings[];
  is_groups: boolean;
  stages?: Stage[];
  // Groups: tint the top-N rows and draw a dashed "top N advance" cut-line.
  advanceCount?: number;
  // Playoff/overall: mark rank 1 as the crowned winner.
  crownTop?: boolean;
}

export function getStandingsStagesQueryOptions(
  tournamentId: number | undefined,
  providedStages: Stage[] | undefined,
  getStages: (id: number) => Promise<Stage[]> = (id) => tournamentService.getStages(id)
) {
  return {
    queryKey: tournamentQueryKeys.stages(tournamentId ?? 0),
    queryFn: () => (tournamentId == null ? Promise.resolve([]) : getStages(tournamentId)),
    enabled: tournamentId != null && providedStages === undefined
  };
}

/**
 * Where the advancing block splits into Upper and Lower bracket, or `null` when
 * it does not split at all.
 *
 * Mirrors `advance_split` (backend `domain/stage/seeds.py`): a later split
 * double elimination sends the top of each group's advancing teams up and the
 * rest down, so a tie ACROSS this line decides who starts a bracket down —
 * every bit as load-bearing as the advance line itself, and invisible until now.
 *
 * Without a dedicated Lower-bracket item the engine halves the concatenated
 * seed list instead of each group's share; that lands on a per-group boundary
 * only when the advancing count is even, so an odd count returns `null` rather
 * than drawing a line this table cannot honestly place.
 */
export function upperBracketCut(
  stages: Stage[],
  groupStage: Stage | null | undefined,
  advanceCount: number
): number | null {
  if (!groupStage || advanceCount < 2) return null;
  const playoff = stages
    .filter(
      (candidate) =>
        candidate.stage_type === "double_elimination" &&
        candidate.split_lower_bracket &&
        (candidate.order > groupStage.order ||
          (candidate.order === groupStage.order && candidate.id > groupStage.id))
    )
    .sort((left, right) => left.order - right.order || left.id - right.id)[0];
  if (!playoff) return null;

  const hasLowerItem = (playoff.items ?? []).some((item) => item.type === "bracket_lower");
  const upper = hasLowerItem
    ? advanceCount - Math.floor(advanceCount / 2)
    : advanceCount % 2 === 0
      ? advanceCount / 2
      : null;
  return upper != null && upper > 0 && upper < advanceCount ? upper : null;
}

type ResultKind = "w" | "l" | "t";

function resultOf(teamId: number, encounter: Encounter): ResultKind {
  const teamScore = encounter.home_team_id === teamId ? encounter.score.home : encounter.score.away;
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

function MapDiff({ diff }: Readonly<{ diff: number }>) {
  const tone = diff > 0 ? "pos" : diff < 0 ? "neg" : "zero";
  const text = diff > 0 ? `+${diff}` : diff < 0 ? `−${Math.abs(diff)}` : "0";
  return <span className={cn("st-diff", tone)}>{text}</span>;
}

function FormChips({ results }: Readonly<{ results: ResultKind[] }>) {
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

function TeamCell({ standing, showGroup }: Readonly<{ standing: Standings; showGroup: boolean }>) {
  const t = useTranslations();
  const groupName = standing.team?.group?.name;
  return (
    <div className="st-team">
      <div className="stack">
        <TeamName team={standing.team} size="xs" nameClassName="nm" />
        {showGroup && groupName && (
          <span className="sub">
            {t("common.group")} {groupName}
          </span>
        )}
      </div>
    </div>
  );
}

const StandingsTable = ({
  standings,
  is_groups,
  stages: providedStages,
  advanceCount = 2,
  crownTop = false
}: StandingTableProps) => {
  const t = useTranslations();

  const tournamentId = standings[0]?.tournament_id;
  const stagesQuery = useQuery(getStandingsStagesQueryOptions(tournamentId, providedStages));
  const stages = providedStages ?? stagesQuery.data ?? [];

  const stage = standings[0]?.stage;
  // Prefer the explicit, admin-configured Stage.advance_count column; fall back
  // to the derived bracket-wiring count.
  let stageCount = stage?.advance_count ?? null;

  if (stageCount == null && stage != null && stages.length > 0) {
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
        stageCount = maxPos;
      }
    }
  }

  // A group may override the stage's number for itself. This table renders one
  // group at a time, so the rendered group's override — when it has one — is
  // the cut-line; everything else keeps the stage-wide resolution above. The
  // standing carries its own group, so the line is right before the separate
  // stages query lands.
  const renderedItemId = standings[0]?.stage_item_id ?? null;
  const itemAdvanceCount =
    standings[0]?.stage_item?.advance_count ??
    (renderedItemId == null
      ? null
      : (stages
          .flatMap((s) => s.items ?? [])
          .find((item) => item.id === renderedItemId)?.advance_count ?? null));

  const resolvedAdvanceCount = itemAdvanceCount ?? stageCount ?? advanceCount;

  const sortedStandings = [...standings].sort((a, b) => {
    const left = is_groups ? a.position : a.overall_position;
    const right = is_groups ? b.position : b.overall_position;
    return left - right;
  });

  const showCut = is_groups && sortedStandings.length > resolvedAdvanceCount;

  // The second boundary inside the advancing block: Upper vs Lower bracket.
  const upperCut = is_groups
    ? upperBracketCut(stages, standings[0]?.stage ?? null, resolvedAdvanceCount)
    : null;
  const showUpperCut = upperCut != null && sortedStandings.length > upperCut;

  // Which clusters are cut by which line. A cluster split by BOTH reports the
  // advance line: being out beats starting a bracket down.
  const tiedAtCut = showCut
    ? straddlingTieGroups(sortedStandings, resolvedAdvanceCount)
    : new Set<number>();
  const tiedAtUpperCut =
    showUpperCut && upperCut != null
      ? straddlingTieGroups(sortedStandings, upperCut)
      : new Set<number>();
  const tieClusterTitle = t("standings.tieCluster");
  const pinnedTitle = t("standings.pinnedPlace");
  const columnCount = is_groups ? 9 : 6;

  // "Ranked by …" legend — resolve metric ids through i18n, falling back to the
  // shared English labels when a key is missing.
  const labelFor = (id: string) => {
    const key = `common.tiebreakerMetrics.${id as TiebreakerMetricId}` as const;
    const label = t(key);
    return label === key ? undefined : label;
  };

  return (
    <div>
      <section
        className={cn("st-scroll", styles.standingsViewport)}
        aria-label={t("tournamentDetail.publicPages.standings.tableLabel")}
        tabIndex={0}
      >
        <table className={cn("st", styles.standingsTable)}>
          <thead>
            {is_groups ? (
              <tr>
                {/* Wide enough for a two-digit rank plus the tie `=` marker,
                    which otherwise wraps under the number. */}
                <th scope="col" className="whitespace-nowrap" style={{ width: 52 }}>
                  #
                </th>
                <th scope="col" className={styles.stickyTeamColumn}>
                  {t("standings.colTeam")}
                </th>
                <th scope="col" className="c" style={{ width: 70 }}>
                  {t("standings.colWDL")}
                </th>
                <th scope="col" className="r" style={{ width: 48 }}>
                  {t("standings.colPts")}
                </th>
                <th scope="col" className="r" style={{ width: 48 }} title={t("common.headToHead")}>
                  {t("standings.colH2H")}
                </th>
                {/* Two numbers, and `13.0 · 17.5` is the widest they get: the
                    column is sized for that so the pair never breaks onto a
                    second line and doubles the row's height. */}
                <th
                  scope="col"
                  className="r whitespace-nowrap"
                  style={{ width: 116 }}
                  title={t("standings.buchholzMedianFull")}
                >
                  {t("common.buchholz")}
                </th>
                <th scope="col" className="r" style={{ width: 54 }} title={t("common.scoreDiff")}>
                  +/−
                </th>
                <th scope="col" className="c" style={{ width: 110 }}>
                  {t("standings.colForm")}
                </th>
                <th scope="col" className="c" style={{ width: 80 }}>
                  <span className="sr-only">{t("common.status")}</span>
                </th>
              </tr>
            ) : (
              <tr>
                <th scope="col" style={{ width: 56 }}>
                  #
                </th>
                <th scope="col" className={styles.stickyTeamColumn}>
                  {t("standings.colTeam")}
                </th>
                <th scope="col" className="c" style={{ width: 90 }}>
                  {t("standings.colRecord")}
                </th>
                <th scope="col" className="r" style={{ width: 170 }}>
                  {t("standings.colMaps")}
                </th>
                <th scope="col" className="r" style={{ width: 80 }}>
                  {t("standings.colMapDiff")}
                </th>
                <th scope="col" className="c" style={{ width: 130 }}>
                  {t("standings.colForm")}
                </th>
              </tr>
            )}
          </thead>
          <tbody>
            {sortedStandings.map((standing, index) => {
              const position = is_groups ? standing.position : standing.overall_position;
              const tieHead = is_groups ? standing.tie_group : null;
              const history = sortStandingsMatches(standing.matches_history ?? []);
              const results = history.map((encounter) => resultOf(standing.team_id, encounter));
              const maps = computeMaps(standing.team_id, history);
              const total = maps.won + maps.lost;
              const wPct = total > 0 ? (maps.won / total) * 100 : 0;
              const advancing = is_groups && position <= resolvedAdvanceCount;
              const crowned = !is_groups && crownTop && position === 1;
              // A tie the line cuts through is the row's real status: whether it
              // advances (or starts a bracket down) is not settled by results.
              const tieVerdict =
                tieHead == null
                  ? null
                  : tiedAtCut.has(tieHead)
                    ? ("advance" as const)
                    : tiedAtUpperCut.has(tieHead)
                      ? ("upper" as const)
                      : null;
              const tieVerdictTitle =
                tieVerdict === "advance"
                  ? t("standings.tieDecidesAdvance")
                  : tieVerdict === "upper"
                    ? t("standings.tieDecidesUpper")
                    : undefined;
              const rowClass = cn(
                crowned ? "crown" : advancing ? "advance" : undefined,
                tieVerdict ? "tie" : undefined
              );

              return (
                <React.Fragment
                  key={`${standing.stage_item_id ?? standing.stage_id ?? "s"}-${standing.team_id}`}
                >
                  <tr className={rowClass || undefined}>
                    <td className="whitespace-nowrap">
                      {/* Every row of a cluster shows its head's position, so
                          4/4/6 reads as "these two were never separated". The
                          next distinct row keeps the position it earned.
                          `tie_group` is a GROUP-relative position, so it means
                          nothing in the overall table, which ranks by
                          `overall_position`. */}
                      <span
                        className="st-rank"
                        title={tieHead != null ? tieClusterTitle : undefined}
                      >
                        {tieHead ?? position}
                      </span>
                      {tieHead != null && (
                        <span
                          className="ml-0.5 text-[color:var(--fg-dim)]"
                          title={tieClusterTitle}
                          aria-label={tieClusterTitle}
                        >
                          =
                        </span>
                      )}
                      {standing.is_pinned && (
                        <span
                          className="ml-1 inline-flex align-[-0.125em] text-[color:var(--fg-dim)]"
                          title={pinnedTitle}
                        >
                          <Lock aria-hidden className="size-3" />
                          <span className="sr-only">{pinnedTitle}</span>
                        </span>
                      )}
                    </td>
                    <td className={styles.stickyTeamColumn}>
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
                        <td className="r tabular-nums text-[color:var(--fg-muted)]">
                          {standing.points.toFixed(1)}
                        </td>
                        <td className="r tabular-nums text-[color:var(--fg-dim)]">
                          {standing.tb ? standing.tb : "—"}
                        </td>
                        <td className="r tabular-nums whitespace-nowrap text-[color:var(--fg-dim)]">
                          {standing.buchholz == null ? (
                            "—"
                          ) : (
                            <>
                              {standing.buchholz.toFixed(1)}
                              {/* Two teams level on the median but split by the
                                  full value can now be read off the table. */}
                              {standing.full_buchholz != null && (
                                <span className="opacity-55">
                                  {" · "}
                                  {standing.full_buchholz.toFixed(1)}
                                </span>
                              )}
                            </>
                          )}
                        </td>
                        <td className="r">
                          <MapDiff diff={standing.score_differential ?? maps.diff} />
                        </td>
                        <td className="c">
                          <FormChips results={results} />
                        </td>
                        <td className="c">
                          {/* The tie IS the status: the line cuts through this
                              cluster, so "advancing" would be a promise the
                              results have not made. */}
                          {tieVerdict ? (
                            <span className="st-status tie" title={tieVerdictTitle}>
                              {t("standings.tieStatus")}
                            </span>
                          ) : advancing ? (
                            <span className="st-status adv">
                              <span className="arrow" />
                              {t("standings.advancing")}
                            </span>
                          ) : (
                            <span className="st-status out">{t("standings.eliminated")}</span>
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

                  {showUpperCut && index === upperCut - 1 && (
                    <tr>
                      <td
                        colSpan={columnCount}
                        className="st-cut st-upper-cut"
                        data-label={t("standings.upperBracketCut", { count: upperCut })}
                      />
                    </tr>
                  )}

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
      </section>
      {is_groups &&
      sortedStandings[0]?.tiebreak_order &&
      sortedStandings[0].tiebreak_order.length > 0 ? (
        <div className="st-footer">
          <span className="label">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ display: "inline-block", verticalAlign: "middle" }}
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" x2="12" y1="16" y2="12" />
              <line x1="12" x2="12.01" y1="8" y2="8" />
            </svg>
            <span>{t("common.tiebreakers")}</span>
          </span>
          <div className="items">
            {sortedStandings[0].tiebreak_order.map((metricId, idx) => {
              const label = tiebreakerLabel(metricId, labelFor);
              return (
                <React.Fragment key={metricId}>
                  {/* Ordering separator beside real text, so it takes the same
                      aria-hidden treatment as the sanctioned "View all →". The
                      rank each badge holds is already in its title. */}
                  {idx > 0 && (
                    <span className="sep" aria-hidden>
                      →
                    </span>
                  )}
                  <span className="badge" title={t("standings.priority", { n: String(idx + 1) })}>
                    {label}
                  </span>
                </React.Fragment>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default StandingsTable;
