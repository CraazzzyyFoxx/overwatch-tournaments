"use client";

import { Fragment, useMemo, useState, type ReactNode } from "react";
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Minus,
  Pencil,
  Shuffle,
  SlidersHorizontal,
  Sprout
} from "lucide-react";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import { HandleLabel } from "@/components/HandleLabel";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import TeamName from "@/components/TeamName";
import { TeamPlacement } from "@/components/TournamentTeamCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { triggerChevronClass } from "@/components/ui/chevron";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { usePermissions } from "@/hooks/usePermissions";
import { useFormatter } from "@/lib/datetime/client";
import { sortTeamPlayers, splitHandle } from "@/lib/player";
import type { RoleOntology } from "@/lib/roster/ontology";
import { groupDisplayName, groupHue } from "@/lib/tournament/group";
import { cn } from "@/lib/utils";
import type {
  PerformanceV2,
  PlayerAnalytics,
  StandingsDistribution,
  TeamAnalytics
} from "@/types/analytics.types";
import type { GlossaryTerm } from "@/disciplines/overwatch/analytics/analytics-glossary";
import { standingsRank } from "@/disciplines/overwatch/analytics/analytics.helpers";
import AnomalyFlag, { AnomalyKinds } from "@/disciplines/overwatch/analytics/components/AnomalyFlag";
import DeltaText, { moveTone } from "@/disciplines/overwatch/analytics/components/DeltaText";
import ExplanationPopover from "@/disciplines/overwatch/analytics/components/ExplanationPopover";
import InfoDot from "@/disciplines/overwatch/analytics/components/InfoDot";
import MoveMark from "@/disciplines/overwatch/analytics/components/MoveMark";
import ChangeShiftDialog from "@/disciplines/overwatch/analytics/components/community/ChangeShiftDialog";

type SortMode = "standings" | "predicted" | "shift";

interface AnalyticsStandingsProps {
  teams: TeamAnalytics[];
  performanceByPlayer: Map<number, PerformanceV2>;
  distributionByTeam?: Map<number, StandingsDistribution>;
  /** The tournament's own role dictionary (its game's metadata): role glyphs, names and roster order. */
  ontology: RoleOntology;
  /** Trailing control on the toolbar row (the list/table view toggle). */
  headerEnd?: ReactNode;
  /** The viewer may read the v2 model: the Impact and vs-similar columns exist only then. */
  canReadV2: boolean;
  /** The tournament is over: places 1–3 are medals. */
  ended: boolean;
  /** Opens a column's glossary entry (the tap path for the explainers). */
  onExplain?: (term: GlossaryTerm) => void;
}

const CELL_CLASS = "px-3 py-2";
const NUM_CLASS = "aqt-tnum text-right";
const ROW_CLASS = "border-[color:var(--aqt-overlay-border)]";

const SIGNED = { maximumFractionDigits: 2, signDisplay: "exceptZero" } as const;

function Head({
  children,
  term,
  onExplain,
  numeric
}: Readonly<{
  children: ReactNode;
  term?: GlossaryTerm;
  onExplain?: (term: GlossaryTerm) => void;
  numeric?: boolean;
}>) {
  return (
    <TableHead scope="col" className={cn("h-9 whitespace-nowrap px-3", numeric && "text-right")}>
      {term ? (
        <span className="inline-flex items-center gap-1">
          {children}
          <InfoDot term={term} onExplain={onExplain} />
        </span>
      ) : (
        children
      )}
    </TableHead>
  );
}

/** The team's summed division forecast as coloured text: arrow, size, unit. */
function TeamForecast({ shift }: Readonly<{ shift: number }>) {
  const t = useTranslations();
  const format = useFormatter();

  if (shift === 0) {
    return (
      <span className="inline-flex items-center gap-1 whitespace-nowrap text-[color:var(--aqt-fg-dim)]">
        <Minus aria-hidden className="size-3.5" />
        {t("analytics.forecast.hold")}
      </span>
    );
  }

  const up = shift > 0;
  const Icon = up ? ArrowUp : ArrowDown;
  return (
    <span
      className="inline-flex items-center gap-1 whitespace-nowrap font-medium"
      style={{ color: moveTone(shift) }}
    >
      <Icon aria-hidden className="size-3.5" />
      <span className="sr-only">{t(up ? "analytics.forecast.up" : "analytics.forecast.down")}</span>
      <span className="aqt-tnum">
        {format.number(Math.abs(shift), { maximumFractionDigits: 1 })}{" "}
        {t("analytics.forecast.divisionUnit")}
      </span>
    </span>
  );
}

/** Nick, faint `#tag`, then the newcomer / new-role marks as `RosterPlayer` draws them. */
function PlayerIdentity({ player }: Readonly<{ player: PlayerAnalytics }>) {
  const t = useTranslations();

  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <HandleLabel handle={player.name} className="font-medium text-[color:var(--aqt-fg)]" />
      {player.is_newcomer ? (
        <IconTooltip label={t("teams.roster.newcomer")} hint={t("teams.roster.newcomerHint")}>
          <Sprout aria-hidden className="size-3.5 text-[color:var(--aqt-rose)]" />
        </IconTooltip>
      ) : null}
      {/* A flex player has no role to be new to (same rule as `RosterPlayer`). */}
      {player.is_newcomer_role && player.role != null ? (
        <IconTooltip label={t("teams.roster.newcomerRole")} hint={t("teams.roster.newcomerRoleHint")}>
          <Shuffle aria-hidden className="size-3.5 text-[color:var(--aqt-amber)]" />
        </IconTooltip>
      ) : null}
    </span>
  );
}

/** One team as its own `<tbody>`: the summary row, then a row per player while open. */
function TeamRows({
  team,
  open,
  onToggle,
  distribution,
  performanceByPlayer,
  ontology,
  canReadV2,
  canEdit,
  ended,
  showGroup,
  onEditShift
}: Readonly<{
  team: TeamAnalytics;
  open: boolean;
  onToggle: () => void;
  distribution?: StandingsDistribution;
  performanceByPlayer: Map<number, PerformanceV2>;
  ontology: RoleOntology;
  canReadV2: boolean;
  canEdit: boolean;
  ended: boolean;
  showGroup: boolean;
  onEditShift: (player: PlayerAnalytics) => void;
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const players = useMemo(() => sortTeamPlayers(team.players, ontology), [team.players, ontology]);
  const tournamentGrid = team.tournament?.division_grid_version;
  const decimal = (value: number, digits = 2) => format.number(value, { maximumFractionDigits: digits });
  // A move is stored in canonical divisions ×100; an unknown one (no earlier ranked tournament) shows a dash.
  const move = (value: number | null) => (value === null ? "—" : decimal(value / 100));
  const percent = (value: number) =>
    format.number(Math.min(1, Math.max(0, value)), { style: "percent" });
  const editLabel = t("analytics.standings.editManualShift");

  // Role … the column before Forecast: the team's identity spans the per-player detail columns.
  const leadSpan = canReadV2 ? 8 : 6;

  const facts: ReactNode[] = [];
  if (distribution) {
    facts.push(
      t("analytics.standings.predictedRange", {
        mean: decimal(distribution.mean_position, 1),
        p10: decimal(distribution.p10_position, 0),
        p90: decimal(distribution.p90_position, 0)
      }),
      `${t("analytics.distribution.top1")} ${percent(distribution.prob_top1)}`
    );
  } else if (team.predicted_place != null) {
    facts.push(t("analytics.standings.predicted", { place: team.predicted_place }));
  }
  if (team.placement_delta != null) {
    facts.push(<DeltaText delta={team.placement_delta} />);
  }

  return (
    <TableBody className="border-t border-[color:var(--aqt-border)]">
      <TableRow className={ROW_CLASS}>
        <TableHead
          scope="rowgroup"
          colSpan={leadSpan}
          className="h-auto px-3 py-2.5 text-caption font-normal normal-case tracking-normal text-[color:var(--aqt-fg)]"
        >
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-expanded={open}
              aria-label={t("analytics.standings.togglePlayers", { team: team.name })}
              onClick={onToggle}
              className="group/trigger"
            >
              <ChevronDown aria-hidden className={triggerChevronClass} />
            </Button>
            <span className="w-8 shrink-0">
              {team.placement != null ? <TeamPlacement placement={team.placement} medal={ended} /> : null}
            </span>
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="flex min-w-0 items-center gap-2">
                <TeamName team={team} size="sm" nameClassName="text-ui font-semibold" />
                {showGroup && team.group?.name ? (
                  <Badge hue={groupHue(team.group.name)} voice="label" className="shrink-0">
                    {groupDisplayName(team.group.name, t("common.group"))}
                  </Badge>
                ) : null}
              </span>
              {facts.length > 0 ? (
                <span className="flex flex-wrap items-center gap-x-1.5 text-caption text-[color:var(--aqt-fg-muted)]">
                  {facts.map((fact, index) => (
                    <Fragment key={index}>
                      {index > 0 ? (
                        <span aria-hidden className="text-[color:var(--aqt-fg-dim)]">
                          ·
                        </span>
                      ) : null}
                      <span>{fact}</span>
                    </Fragment>
                  ))}
                </span>
              ) : null}
              {/* The roster at a glance: role glyph + nick, as the Teams list draws it. */}
              <span
                className="block max-w-[24rem] truncate text-caption text-[color:var(--aqt-fg-muted)]"
                title={players.map((player) => splitHandle(player.name).name).join(", ")}
              >
                {players.map((player) => (
                  <span key={player.id} className="mr-3 last:mr-0">
                    {/* Inline, not flex: `truncate` can only ellipsize plain text runs. */}
                    <span className="mr-1 inline-block align-[-2px]">
                      <PlayerRoleIcon role={player.role} ontology={ontology} size={13} decorative />
                    </span>
                    {splitHandle(player.name).name}
                  </span>
                ))}
              </span>
            </span>
            <span className="aqt-tnum shrink-0 text-ui font-semibold">
              <span className="sr-only">{t("analytics.standings.record")} </span>
              {format.number(team.wins)}–{format.number(team.losses)}
            </span>
          </div>
        </TableHead>
        <TableCell className={CELL_CLASS}>
          <TeamForecast shift={team.total_shift} />
        </TableCell>
        <TableCell className={cn(CELL_CLASS, NUM_CLASS)}>{percent(team.avg_confidence)}</TableCell>
        <TableCell className={cn(CELL_CLASS, "text-right")}>
          {team.manual_shift_points !== 0 ? (
            <IconTooltip
              label={t("analytics.standings.manual")}
              hint={t("analytics.standings.shiftBreakdownTooltip", {
                balancer: decimal(team.balancer_shift, 1),
                manual: decimal(team.manual_shift, 1)
              })}
              className="align-middle text-[color:var(--aqt-fg-muted)]"
            >
              <SlidersHorizontal aria-hidden className="size-3.5" />
            </IconTooltip>
          ) : null}
        </TableCell>
        <TableCell className={CELL_CLASS}>
          <AnomalyKinds anomalies={team.anomalies} />
        </TableCell>
      </TableRow>
      {open
        ? players.map((player) => {
            const performance = canReadV2 ? performanceByPlayer.get(player.id) : undefined;
            return (
              <TableRow key={player.id} className={cn(ROW_CLASS, "bg-[color:var(--aqt-overlay-1)]")}>
                <TableCell className={CELL_CLASS}>
                  <PlayerRoleIcon role={player.role} ontology={ontology} size={18} />
                </TableCell>
                <TableCell className={CELL_CLASS}>
                  <PlayerIdentity player={player} />
                </TableCell>
                <TableCell className={CELL_CLASS}>
                  <DivisionIcon division={player.division} tournamentGrid={tournamentGrid} width={22} height={22} tooltip />
                </TableCell>
                <TableCell className={cn(CELL_CLASS, NUM_CLASS)}>{move(player.move_2)}</TableCell>
                <TableCell className={cn(CELL_CLASS, NUM_CLASS)}>{move(player.move_1)}</TableCell>
                <TableCell className={cn(CELL_CLASS, NUM_CLASS)}>{format.number(player.points, SIGNED)}</TableCell>
                {canReadV2 ? (
                  <>
                    <TableCell className={cn(CELL_CLASS, NUM_CLASS)}>
                      {performance ? (
                        <span className="inline-flex items-center gap-1">
                          {decimal(performance.impact_score, 0)}
                          {/* No algorithmId: SHAP explanations come from the Performance ML v2
                              algorithm, not the selected shift algorithm, so the latest one is right. */}
                          <ExplanationPopover playerId={player.id} tournamentId={player.tournament_id} />
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell className={cn(CELL_CLASS, NUM_CLASS)}>
                      {performance ? (
                        <span
                          title={t("analytics.standings.localPercentileTitle", {
                            value: decimal(performance.local_percentile, 0),
                            n: performance.local_reference_n
                          })}
                        >
                          {format.number(performance.local_zscore, SIGNED)}
                        </span>
                      ) : null}
                    </TableCell>
                  </>
                ) : null}
                <TableCell className={CELL_CLASS}>
                  <MoveMark
                    direction={player.predicted_direction}
                    target={player.predicted_division ?? player.division}
                    tournamentGrid={tournamentGrid}
                    withWord={false}
                  />
                </TableCell>
                <TableCell className={cn(CELL_CLASS, NUM_CLASS)}>{percent(player.confidence)}</TableCell>
                <TableCell className={cn(CELL_CLASS, NUM_CLASS)}>
                  <span className="inline-flex items-center gap-1">
                    {decimal(player.shift)}
                    {canEdit ? (
                      <IconTooltip label={editLabel} control>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          aria-label={editLabel}
                          onClick={() => onEditShift(player)}
                        >
                          <Pencil aria-hidden />
                        </Button>
                      </IconTooltip>
                    ) : null}
                  </span>
                </TableCell>
                <TableCell className={CELL_CLASS}>
                  {player.anomalies.length > 0 ? (
                    <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                      {player.anomalies.map((anomaly, index) => (
                        <AnomalyFlag
                          key={`${player.id}-${anomaly.kind}-${index}`}
                          kind={anomaly.kind}
                          reasons={anomaly.reasons}
                          label="short"
                        />
                      ))}
                    </span>
                  ) : null}
                </TableCell>
              </TableRow>
            );
          })
        : null}
    </TableBody>
  );
}

const sortedTeams = (teams: TeamAnalytics[], mode: SortMode) => {
  if (mode === "predicted") {
    return [...teams].sort(
      (left, right) =>
        (left.predicted_place ?? Number.MAX_SAFE_INTEGER) -
          (right.predicted_place ?? Number.MAX_SAFE_INTEGER) ||
        left.name.localeCompare(right.name)
    );
  }

  if (mode === "shift") {
    return [...teams].sort(
      (left, right) =>
        Math.abs(right.total_shift) - Math.abs(left.total_shift) || left.name.localeCompare(right.name)
    );
  }

  return [...teams].sort(
    (left, right) => standingsRank(left) - standingsRank(right) || left.name.localeCompare(right.name)
  );
};

/**
 * The Table view: a sort toolbar, then one table where every team is a
 * `<tbody>` (summary row, its players while open). The table scrolls inside its
 * own labelled region, so the page never does.
 */
const AnalyticsStandings = ({
  teams,
  performanceByPlayer,
  distributionByTeam,
  ontology,
  headerEnd,
  canReadV2,
  ended,
  onExplain
}: AnalyticsStandingsProps) => {
  const t = useTranslations();
  const { hasPermission } = usePermissions();
  const canEdit = hasPermission("analytics.update");
  const [mode, setMode] = useState<SortMode>("standings");
  const [expandedId, setExpandedId] = useState<number | null>(teams[0]?.id ?? null);
  const [editingPlayer, setEditingPlayer] = useState<PlayerAnalytics | null>(null);
  const visibleTeams = useMemo(() => sortedTeams(teams, mode), [teams, mode]);
  // A group chip only tells rows apart when they span more than one group.
  const showGroup = useMemo(
    () => new Set(teams.map((team) => team.group?.name).filter(Boolean)).size > 1,
    [teams]
  );

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ToggleGroup
          variant="pill"
          size="sm"
          value={mode}
          onValueChange={(next) => next && setMode(next as SortMode)}
          aria-label={t("analytics.standings.sortLabel")}
        >
          <ToggleGroupItem value="standings">{t("analytics.standings.sortStandings")}</ToggleGroupItem>
          <ToggleGroupItem value="predicted">{t("analytics.standings.sortPredicted")}</ToggleGroupItem>
          <ToggleGroupItem value="shift">{t("analytics.standings.sortShift")}</ToggleGroupItem>
        </ToggleGroup>
        {headerEnd}
      </div>
      <Card>
        <div
          role="region"
          aria-label={t("analytics.standings.title")}
          tabIndex={0}
          className="overflow-x-auto rounded-[inherit] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
        >
          <Table wrapperClassName="overflow-visible">
            <TableHeader>
              <TableRow>
                <Head>{t("analytics.standings.colRole")}</Head>
                <Head>{t("analytics.standings.colBattleTag")}</Head>
                <Head>{t("analytics.standings.colCurrent")}</Head>
                <Head term="recent_moves" onExplain={onExplain} numeric>
                  {t("analytics.standings.colMove2")}
                </Head>
                <Head numeric>{t("analytics.standings.colMove1")}</Head>
                <Head term="points" onExplain={onExplain} numeric>
                  {t("analytics.standings.colSignal")}
                </Head>
                {canReadV2 ? (
                  <>
                    <Head term="impact" onExplain={onExplain} numeric>
                      {t("analytics.standings.colImpact")}
                    </Head>
                    <Head term="vs_local" onExplain={onExplain} numeric>
                      {t("analytics.standings.colVsLocal")}
                    </Head>
                  </>
                ) : null}
                <Head term="predicted_move" onExplain={onExplain}>
                  {t("analytics.standings.colForecast")}
                </Head>
                <Head term="confidence" onExplain={onExplain} numeric>
                  {t("analytics.standings.colConfidence")}
                </Head>
                <Head term="shift" onExplain={onExplain} numeric>
                  {t("analytics.standings.colManual")}
                </Head>
                <Head term="watch" onExplain={onExplain}>
                  {t("analytics.standings.colFlags")}
                </Head>
              </TableRow>
            </TableHeader>
            {visibleTeams.map((team) => (
              <TeamRows
                key={team.id}
                team={team}
                open={expandedId === team.id}
                onToggle={() => setExpandedId((current) => (current === team.id ? null : team.id))}
                distribution={distributionByTeam?.get(team.id)}
                performanceByPlayer={performanceByPlayer}
                ontology={ontology}
                canReadV2={canReadV2}
                canEdit={canEdit}
                ended={ended}
                showGroup={showGroup}
                onEditShift={setEditingPlayer}
              />
            ))}
          </Table>
        </div>
      </Card>
      {editingPlayer ? (
        <ChangeShiftDialog
          player={editingPlayer}
          open
          onOpenChange={(open) => {
            if (!open) setEditingPlayer(null);
          }}
        />
      ) : null}
    </div>
  );
};

export default AnalyticsStandings;
