import React from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronUp, Info, Lock, Trophy } from "lucide-react";

import { Encounter } from "@/types/encounter.types";
import { Stage, StageItem, Standings } from "@/types/tournament.types";
import { cn } from "@/lib/utils";
import { sortStandingsMatches } from "@/lib/tournament/match-order";
import { groupDisplayName } from "@/lib/tournament/group";
import { straddlingTieGroups } from "@/lib/tournament/tie-clusters";
import { useTranslations } from "next-intl";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import {
  FFA_STAT_PREFIX,
  tiebreakerLabel,
  type TiebreakerMetricId
} from "@/lib/tournament/tiebreakers";
import tournamentService from "@/services/tournament.service";
import TeamName from "@/components/TeamName";
import { ResTag, type ResTagKind } from "@/components/match/cells";
import { Badge } from "@/components/ui/badge";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

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
 * Mirrors the backend's per-group rule (`group_advance_counts`,
 * `domain/stage/seeds.py`): places `1…advance_upper_count` are seeded into the
 * upper bracket and the rest straight into the lower one, so a tie ACROSS this
 * line decides who starts a bracket down — every bit as load-bearing as the
 * advance line itself, and invisible until now.
 *
 * The group's own number wins over the stage's; `null` on both means every
 * advancing team starts upper, and there is no line to draw. Which playoff
 * consumes the seeds no longer matters: the split is configured here.
 */
export function upperBracketCut(
  groupStage: Stage | null | undefined,
  item: StageItem | null,
  advanceCount: number | null
): number | null {
  if (!groupStage || advanceCount == null) return null;
  const upper = item?.advance_upper_count ?? groupStage.advance_upper_count;
  return upper != null && upper > 0 && upper < advanceCount ? upper : null;
}

type ResultKind = "w" | "l" | "t";

/** A tie is a draw square (`ResTag` "d") that keeps its own letter. */
const RES_TAG_KIND: Record<ResultKind, ResTagKind> = { w: "w", l: "l", t: "d" };

/** The row's place against the lines: the crowned winner, a tie a line cuts, the advancing block. */
type Zone = "crown" | "tie" | "advance";

const ROW_TINT: Record<Zone, string> = {
  crown:
    "bg-[color:color-mix(in_srgb,var(--aqt-medal-gold)_6%,transparent)] hover:bg-[color:color-mix(in_srgb,var(--aqt-medal-gold)_10%,transparent)]",
  tie: "bg-[color:color-mix(in_srgb,var(--aqt-amber)_8%,transparent)] hover:bg-[color:color-mix(in_srgb,var(--aqt-amber)_13%,transparent)]",
  advance:
    "bg-[color:color-mix(in_srgb,var(--aqt-teal)_5%,transparent)] hover:bg-[color:color-mix(in_srgb,var(--aqt-teal)_9%,transparent)]"
};

const RANK_TONE: Record<Zone, string> = {
  crown: "text-[color:var(--aqt-medal-gold)]",
  tie: "text-[color:var(--aqt-amber)]",
  advance: "text-[color:var(--aqt-teal)]"
};

const CELL = "px-2.5 py-2.75";
const HEAD = "h-auto px-2.5 py-2.5 whitespace-nowrap";

/**
 * The team column stays put while the row scrolls under it. Opaque, so the
 * cells sliding beneath never show through, and ruled on its right edge by a
 * pseudo-element: a collapsed table's own border would not travel with it.
 */
const STICKY_TEAM =
  "sticky left-0 z-2 bg-[color:var(--aqt-card)] after:absolute after:inset-y-0 after:right-0 after:w-px after:bg-[color:var(--aqt-border)]";

/** A dashed rule across the table, its `data-label` centred on it. */
const CUT_LINE =
  "relative h-0 before:absolute before:inset-x-3.5 before:top-0 before:border-t-[1.5px] before:border-dashed before:border-[color:color-mix(in_srgb,var(--aqt-teal)_40%,transparent)] after:absolute after:left-1/2 after:top-1/2 after:-translate-x-1/2 after:-translate-y-1/2 after:whitespace-nowrap after:bg-[color:var(--aqt-card)] after:px-2.5 after:py-0.5 after:font-[family-name:var(--aqt-data)] after:text-label after:font-bold after:uppercase after:tracking-label after:text-[color:var(--aqt-teal)] after:content-[attr(data-label)]";

/** The team's own seat and what the other seats scored, from the encounter's participations. */
function seatScores(teamId: number, encounter: Encounter): { own: number; others: number[] } {
  const seats = encounter.teams ?? [];
  return {
    own: seats.find((seat) => seat.team_id === teamId)?.score ?? 0,
    others: seats.filter((seat) => seat.team_id !== teamId).map((seat) => seat.score)
  };
}

function resultOf(teamId: number, encounter: Encounter): ResultKind {
  const { own, others } = seatScores(teamId, encounter);
  const best = Math.max(...others, 0);
  if (own === best) return "t";
  return own > best ? "w" : "l";
}

function computeMaps(teamId: number, history: Encounter[]) {
  let won = 0;
  let lost = 0;
  for (const encounter of history) {
    const { own, others } = seatScores(teamId, encounter);
    won += own;
    lost += others.reduce((sum, score) => sum + score, 0);
  }
  return { won, lost, diff: won - lost };
}

function MapDiff({ diff }: Readonly<{ diff: number }>) {
  const tone =
    diff > 0
      ? "text-[color:var(--aqt-emerald)]"
      : diff < 0
        ? "text-[color:var(--aqt-rose)]"
        : "text-[color:var(--aqt-fg-dim)]";
  const text = diff > 0 ? `+${diff}` : diff < 0 ? `−${Math.abs(diff)}` : "0";
  return (
    <span data-diff className={cn("aqt-tnum text-caption font-bold", tone)}>
      {text}
    </span>
  );
}

function FormChips({ results }: Readonly<{ results: ResultKind[] }>) {
  if (results.length === 0) {
    return <span className="text-[color:var(--aqt-fg-faint)]">—</span>;
  }
  return (
    <span data-form className="inline-flex gap-0.75">
      {results.slice(-5).map((result, index) => (
        <ResTag key={index} kind={RES_TAG_KIND[result]}>
          {result.toUpperCase()}
        </ResTag>
      ))}
    </span>
  );
}

function TeamCell({ standing, showGroup }: Readonly<{ standing: Standings; showGroup: boolean }>) {
  const t = useTranslations();
  const groupName = standing.team?.group?.name;
  // A team a Swiss threshold eliminated keeps its place in the table, read as done.
  const eliminated = standing.swiss_status === "eliminated";
  return (
    <div className="flex min-w-32.5 items-center gap-3">
      <div className="flex flex-col gap-0.5">
        <TeamName
          team={standing.team}
          size="xs"
          nameClassName={cn(
            "font-display text-body leading-tight font-bold",
            eliminated ? "text-[color:var(--aqt-fg-dim)]" : "text-[color:var(--aqt-fg)]"
          )}
        />
        {showGroup && groupName && (
          <span className="aqt-tnum text-label leading-tight text-[color:var(--aqt-fg-dim)]">
            {groupDisplayName(groupName, t("common.group"))}
          </span>
        )}
      </div>
      {/* A Swiss threshold's verdict, the server's: final, unlike the cut-line. */}
      {standing.swiss_status === "qualified" ? (
        <Badge data-status voice="label" tone="accent">
          {t("standings.swissQualified")}
        </Badge>
      ) : eliminated ? (
        <Badge data-status voice="label" tone="neutral">
          {t("standings.swissEliminated")}
        </Badge>
      ) : null}
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
  const renderedItem =
    standings[0]?.stage_item ??
    (renderedItemId == null
      ? null
      : (stages.flatMap((s) => s.items ?? []).find((item) => item.id === renderedItemId) ?? null));
  const itemAdvanceCount = renderedItem?.advance_count ?? null;

  const resolvedAdvanceCount = itemAdvanceCount ?? stageCount ?? advanceCount;

  const sortedStandings = [...standings].sort((a, b) => {
    const left = is_groups ? a.position : a.overall_position;
    const right = is_groups ? b.position : b.overall_position;
    return left - right;
  });

  const showCut = is_groups && sortedStandings.length > resolvedAdvanceCount;

  // The second boundary inside the advancing block: Upper vs Lower bracket.
  const upperCut = is_groups
    ? upperBracketCut(standings[0]?.stage ?? null, renderedItem, resolvedAdvanceCount)
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
  // A column sum names the organizer's column: its label comes from the stage
  // this table already loads (`stages`, above); the bare key stands in only
  // while that query is still in flight.
  const scoringColumns =
    stages.find((candidate) => candidate.id === stage?.id)?.scoring.columns ?? [];
  const labelFor = (id: string) => {
    if (id.startsWith(FFA_STAT_PREFIX)) {
      const columnKey = id.slice(FFA_STAT_PREFIX.length);
      const column = scoringColumns.find((candidate) => candidate.key === columnKey);
      return t("common.tiebreakerMetrics.ffa_stat", { label: column?.label ?? columnKey });
    }
    const key = `common.tiebreakerMetrics.${id as TiebreakerMetricId}` as const;
    const label = t(key);
    return label === key ? undefined : label;
  };

  return (
    <div>
      <section
        className="relative w-full min-w-0 max-w-full overflow-x-auto overflow-y-clip overscroll-x-contain [scrollbar-width:none] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)] [&::-webkit-scrollbar]:hidden"
        aria-label={t("tournamentDetail.publicPages.standings.tableLabel")}
        tabIndex={0}
      >
        <Table wrapperClassName="overflow-visible" className="min-w-184">
          <TableHeader>
            {is_groups ? (
              <TableRow>
                {/* Wide enough for a two-digit rank plus the tie `=` marker,
                    which otherwise wraps under the number. */}
                <TableHead scope="col" className={HEAD} style={{ width: 52 }}>
                  #
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, STICKY_TEAM, "z-3")}>
                  {t("standings.colTeam")}
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, "text-center")} style={{ width: 70 }}>
                  {t("standings.colWDL")}
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, "text-right")} style={{ width: 48 }}>
                  {t("standings.colPts")}
                </TableHead>
                <TableHead
                  scope="col"
                  className={cn(HEAD, "text-right")}
                  style={{ width: 48 }}
                  title={t("common.headToHead")}
                >
                  {t("standings.colH2H")}
                </TableHead>
                {/* Two numbers, and `13.0 · 17.5` is the widest they get: the
                    column is sized for that so the pair never breaks onto a
                    second line and doubles the row's height. */}
                <TableHead
                  scope="col"
                  className={cn(HEAD, "text-right")}
                  style={{ width: 116 }}
                  title={t("standings.buchholzMedianFull")}
                >
                  {t("common.buchholz")}
                </TableHead>
                <TableHead
                  scope="col"
                  className={cn(HEAD, "text-right")}
                  style={{ width: 54 }}
                  title={t("common.scoreDiff")}
                >
                  +/−
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, "text-center")} style={{ width: 110 }}>
                  {t("standings.colForm")}
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, "text-center")} style={{ width: 80 }}>
                  <span className="sr-only">{t("common.status")}</span>
                </TableHead>
              </TableRow>
            ) : (
              <TableRow>
                <TableHead scope="col" className={HEAD} style={{ width: 56 }}>
                  #
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, STICKY_TEAM, "z-3")}>
                  {t("standings.colTeam")}
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, "text-center")} style={{ width: 90 }}>
                  {t("standings.colRecord")}
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, "text-right")} style={{ width: 170 }}>
                  {t("standings.colMaps")}
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, "text-right")} style={{ width: 80 }}>
                  {t("standings.colMapDiff")}
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, "text-center")} style={{ width: 130 }}>
                  {t("standings.colForm")}
                </TableHead>
              </TableRow>
            )}
          </TableHeader>
          <TableBody>
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
              // The row is amber even while it is provisionally advancing,
              // because that is exactly what is unsettled.
              const zone: Zone | null = crowned
                ? "crown"
                : tieVerdict
                  ? "tie"
                  : advancing
                    ? "advance"
                    : null;

              return (
                <React.Fragment
                  key={`${standing.stage_item_id ?? standing.stage_id ?? "s"}-${standing.team_id}`}
                >
                  <TableRow
                    data-advance={advancing || undefined}
                    data-tie={tieVerdict ?? undefined}
                    className={zone ? ROW_TINT[zone] : undefined}
                  >
                    <TableCell className={cn(CELL, "whitespace-nowrap")}>
                      {crowned && (
                        <Trophy
                          aria-hidden
                          className="mr-1.5 inline size-3.5 align-[-0.125em] text-[color:var(--aqt-medal-gold)]"
                        />
                      )}
                      {/* Every row of a cluster shows its head's position, so
                          4/4/6 reads as "these two were never separated". The
                          next distinct row keeps the position it earned.
                          `tie_group` is a GROUP-relative position, so it means
                          nothing in the overall table, which ranks by
                          `overall_position`. */}
                      <span
                        data-rank
                        className={cn(
                          "inline-block min-w-6 font-display text-title leading-none font-extrabold tabular-nums",
                          standing.swiss_status === "eliminated"
                            ? "text-[color:var(--aqt-fg-dim)]"
                            : zone
                              ? RANK_TONE[zone]
                              : "text-[color:var(--aqt-fg-faint)]"
                        )}
                        title={tieHead != null ? tieClusterTitle : undefined}
                      >
                        {tieHead ?? position}
                      </span>
                      {tieHead != null && (
                        <span
                          className="ml-0.5 text-[color:var(--aqt-fg-dim)]"
                          title={tieClusterTitle}
                          aria-label={tieClusterTitle}
                        >
                          =
                        </span>
                      )}
                      {standing.is_pinned && (
                        <span
                          className="ml-1 inline-flex align-[-0.125em] text-[color:var(--aqt-fg-dim)]"
                          title={pinnedTitle}
                        >
                          <Lock aria-hidden className="size-3" />
                          <span className="sr-only">{pinnedTitle}</span>
                        </span>
                      )}
                    </TableCell>
                    <TableCell className={cn(CELL, STICKY_TEAM)}>
                      <TeamCell standing={standing} showGroup={!is_groups} />
                    </TableCell>
                    <TableCell className={cn(CELL, "text-center")}>
                      <span className="aqt-tnum inline-flex items-baseline gap-1 text-body font-semibold">
                        <span className="text-[color:var(--aqt-emerald)]">{standing.win}</span>
                        <span className="text-[color:var(--aqt-fg-faint)]">·</span>
                        <span className="text-[color:var(--aqt-amber)]">{standing.draw}</span>
                        <span className="text-[color:var(--aqt-fg-faint)]">·</span>
                        <span className="text-[color:var(--aqt-fg-dim)]">{standing.lose}</span>
                      </span>
                    </TableCell>

                    {is_groups ? (
                      <>
                        <TableCell
                          className={cn(CELL, "text-right tabular-nums text-[color:var(--aqt-fg-muted)]")}
                        >
                          {standing.points.toFixed(1)}
                        </TableCell>
                        <TableCell
                          className={cn(CELL, "text-right tabular-nums text-[color:var(--aqt-fg-dim)]")}
                        >
                          {standing.tb ? standing.tb : "—"}
                        </TableCell>
                        <TableCell
                          className={cn(
                            CELL,
                            "whitespace-nowrap text-right tabular-nums text-[color:var(--aqt-fg-dim)]"
                          )}
                        >
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
                        </TableCell>
                        <TableCell className={cn(CELL, "text-right")}>
                          <MapDiff diff={standing.score_differential ?? maps.diff} />
                        </TableCell>
                        <TableCell className={cn(CELL, "text-center")}>
                          <FormChips results={results} />
                        </TableCell>
                        <TableCell className={cn(CELL, "text-center")}>
                          {/* The tie IS the status: the line cuts through this
                              cluster, so "advancing" would be a promise the
                              results have not made. */}
                          {tieVerdict ? (
                            <Badge data-status voice="label" tone="warning" title={tieVerdictTitle}>
                              {t("standings.tieStatus")}
                            </Badge>
                          ) : advancing ? (
                            <Badge data-status voice="label" tone="accent">
                              <ChevronUp aria-hidden className="size-3" />
                              {t("standings.advancing")}
                            </Badge>
                          ) : (
                            <Badge data-status voice="label" tone="neutral">
                              {t("standings.eliminated")}
                            </Badge>
                          )}
                        </TableCell>
                      </>
                    ) : (
                      <>
                        <TableCell className={cn(CELL, "text-right")}>
                          <span className="flex items-center justify-end gap-2.25">
                            <span className="aqt-tnum min-w-12.5 text-right text-caption font-semibold text-[color:var(--aqt-fg-muted)]">
                              {maps.won}–{maps.lost}
                            </span>
                            {/* The map split: won emerald, lost rose. */}
                            <span className="flex h-1.5 w-22.5 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)]">
                              <span
                                className="h-full bg-[color:var(--aqt-emerald)]"
                                style={{ width: `${wPct}%` }}
                              />
                              <span
                                className="h-full bg-[color:color-mix(in_srgb,var(--aqt-rose)_40%,transparent)]"
                                style={{ width: `${100 - wPct}%` }}
                              />
                            </span>
                          </span>
                        </TableCell>
                        <TableCell className={cn(CELL, "text-right")}>
                          <MapDiff diff={maps.diff} />
                        </TableCell>
                        <TableCell className={cn(CELL, "text-center")}>
                          <FormChips results={results} />
                        </TableCell>
                      </>
                    )}
                  </TableRow>

                  {showUpperCut && index === upperCut - 1 && (
                    <TableRow>
                      <TableCell
                        colSpan={columnCount}
                        className={cn(CELL, CUT_LINE)}
                        data-cut="upper"
                        data-label={t("standings.upperBracketCut", { count: upperCut })}
                      />
                    </TableRow>
                  )}

                  {showCut && index === resolvedAdvanceCount - 1 && (
                    <TableRow>
                      <TableCell
                        colSpan={columnCount}
                        className={cn(CELL, CUT_LINE)}
                        data-cut="advance"
                        data-label={t("common.topAdvance", { count: resolvedAdvanceCount })}
                      />
                    </TableRow>
                  )}
                </React.Fragment>
              );
            })}
          </TableBody>
        </Table>
      </section>
      {is_groups &&
      sortedStandings[0]?.tiebreak_order &&
      sortedStandings[0].tiebreak_order.length > 0 ? (
        <div className="flex items-center gap-3 border-t border-[color:var(--aqt-border)] px-4.5 py-3 text-label max-sm:flex-col max-sm:items-start max-sm:gap-2">
          <Eyebrow className="inline-flex items-center gap-1.5 whitespace-nowrap">
            <Info aria-hidden className="size-3.25" />
            <span>{t("common.tiebreakers")}</span>
          </Eyebrow>
          <div className="flex flex-wrap items-center gap-1.5">
            {sortedStandings[0].tiebreak_order.map((metricId, idx) => {
              const label = tiebreakerLabel(metricId, labelFor);
              return (
                <React.Fragment key={metricId}>
                  {/* Ordering separator beside real text, so it takes the same
                      aria-hidden treatment as the sanctioned "View all →". The
                      rank each metric holds is already in its title. */}
                  {idx > 0 && (
                    <span className="text-[color:var(--aqt-fg-faint)]" aria-hidden>
                      →
                    </span>
                  )}
                  <span
                    className="font-medium text-[color:var(--aqt-fg-dim)]"
                    title={t("standings.priority", { n: String(idx + 1) })}
                  >
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
