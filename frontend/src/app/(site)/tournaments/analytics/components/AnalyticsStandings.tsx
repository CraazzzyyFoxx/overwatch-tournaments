import React, { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ChevronRight, Minus } from "lucide-react";
import {
  AnalyticsAnomaly,
  PerformanceV2,
  PlayerAnalytics,
  StandingsDistribution,
  TeamAnalytics
} from "@/types/analytics.types";
import type { DivisionGridVersion } from "@/types/workspace.types";
import {
  confidenceWord,
  formatAnalyticsNumber,
  formatConfidencePercent
} from "@/app/(site)/tournaments/analytics/analytics.helpers";
import AnomalyTooltip from "@/app/(site)/tournaments/analytics/components/AnomalyTooltip";
import ExplanationPopover from "@/app/(site)/tournaments/analytics/components/ExplanationPopover";
import ForecastChip from "@/app/(site)/tournaments/analytics/components/ForecastChip";
import MetricTooltip from "@/app/(site)/tournaments/analytics/components/MetricTooltip";
import { useTranslation } from "@/i18n/LanguageContext";
import { sortTeamPlayers } from "@/utils/player";
import { cn } from "@/lib/utils";
import { usePermissions } from "@/hooks/usePermissions";
import analyticsService from "@/services/analytics.service";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import styles from "./AnalyticsRedesign.module.css";

type SortMode = "standings" | "predicted" | "shift";

interface AnalyticsStandingsProps {
  teams: TeamAnalytics[];
  performanceByPlayer: Map<number, PerformanceV2>;
  distributionByTeam?: Map<number, StandingsDistribution>;
}

const anomalyHue: Record<string, string> = {
  smurf: "350 84% 65%",
  troll: "38 92% 60%",
  throw: "2 75% 62%",
  sandbag: "275 72% 68%"
};

const AnomalyChip = ({ anomaly, label }: { anomaly?: AnalyticsAnomaly; label?: string }) => {
  const kind = label ?? anomaly?.kind ?? "manual";
  const hue = anomaly ? (anomalyHue[anomaly.kind] ?? "199 90% 60%") : "38 92% 60%";

  const chip = (
    <span className={styles.chip}>
      <span className={styles.chipDot} style={{ background: `hsl(${hue})` }} />
      {kind}
    </span>
  );

  // Anomaly chips get a decoded tooltip; the manual-shift chip stays plain.
  if (!anomaly) {
    return chip;
  }

  return (
    <AnomalyTooltip kind={anomaly.kind} reasons={anomaly.reasons} focusable={false}>
      {chip}
    </AnomalyTooltip>
  );
};

const DivisionBadge = ({
  division,
  tournamentGrid,
  dimmed,
  size = 26
}: {
  division: number | null;
  tournamentGrid?: DivisionGridVersion | null;
  dimmed?: boolean;
  size?: number;
}) => {
  if (division == null) {
    return <span className="text-muted-foreground">-</span>;
  }

  return (
    <DivisionIcon
      division={division}
      tournamentGrid={tournamentGrid}
      width={size}
      height={size}
      className={cn("inline-block", dimmed && "opacity-45")}
    />
  );
};

const DivisionMove = ({
  player,
  tournamentGrid
}: {
  player: PlayerAnalytics;
  tournamentGrid?: DivisionGridVersion | null;
}) => {
  const arrow = player.predicted_direction === "promote"
    ? "up"
    : player.predicted_direction === "demote"
      ? "down"
      : "flat";

  return (
    <span className={styles.divisionMove}>
      <DivisionBadge division={player.division} tournamentGrid={tournamentGrid} />
      <span
        className={cn(
          "text-xs font-bold",
          arrow === "up" && styles.trendPositive,
          arrow === "down" && styles.trendNegative,
          arrow === "flat" && "text-muted-foreground"
        )}
      >
        {arrow === "up" ? (
          <ArrowUp className="h-3.5 w-3.5" />
        ) : arrow === "down" ? (
          <ArrowDown className="h-3.5 w-3.5" />
        ) : (
          <Minus className="h-3.5 w-3.5" />
        )}
      </span>
      <DivisionBadge
        division={player.predicted_division ?? player.division}
        tournamentGrid={tournamentGrid}
        dimmed={player.predicted_direction === "flat"}
      />
    </span>
  );
};

const ChangeDivisionModal = ({
  player,
  open,
  setOpen
}: {
  player: PlayerAnalytics;
  open: boolean;
  setOpen: (open: boolean) => void;
}) => {
  const [division, setDivision] = useState(player.shift ?? 0);
  const queryClient = useQueryClient();

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    await analyticsService.patchPlayerShift(player.team_id, player.id, division);
    await queryClient.invalidateQueries({ queryKey: ["analytics"] });
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>Edit manual shift</DialogTitle>
        </DialogHeader>
        <form onSubmit={onSubmit} className="grid gap-4">
          <div className="grid grid-cols-4 items-center gap-4">
            <Label htmlFor={`analytics-shift-${player.id}`} className="text-right">
              Shift
            </Label>
            <Input
              id={`analytics-shift-${player.id}`}
              value={division}
              className="col-span-3"
              type="number"
              onChange={(event) => setDivision(Number(event.target.value))}
            />
          </div>
          <DialogFooter>
            <Button type="submit">Save changes</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

const TeamDetail = ({
  team,
  performanceByPlayer
}: {
  team: TeamAnalytics;
  performanceByPlayer: Map<number, PerformanceV2>;
}) => {
  const [editingPlayer, setEditingPlayer] = useState<PlayerAnalytics | null>(null);
  const { hasPermission } = usePermissions();
  const { t } = useTranslation();
  const canEdit = hasPermission("analytics.update");
  const tournamentGrid = team.tournament?.division_grid_version;
  const players = useMemo(() => sortTeamPlayers(team.players), [team.players]);

  return (
    <div className={styles.teamDetail}>
      <div className={styles.detailTableWrap}>
        <table className={styles.detailTable}>
          <thead>
            <tr>
              <th>{t("analytics.standings.colRole")}</th>
              <th>{t("analytics.standings.colBattleTag")}</th>
              <th className={styles.center}>{t("analytics.standings.colCurrent")}</th>
              <th className={styles.center}>{t("analytics.standings.colForecast")}</th>
              <th className={styles.center}>
                <MetricTooltip term="recent_moves" showIcon>
                  {t("analytics.standings.colMove2")}
                </MetricTooltip>
              </th>
              <th className={styles.center}>
                <MetricTooltip term="recent_moves" showIcon>
                  {t("analytics.standings.colMove1")}
                </MetricTooltip>
              </th>
              <th className={styles.center}>
                <MetricTooltip term="points" showIcon>
                  {t("analytics.standings.colSignal")}
                </MetricTooltip>
              </th>
              <th className={styles.center}>
                <MetricTooltip term="impact" showIcon>
                  {t("analytics.standings.colImpact")}
                </MetricTooltip>
              </th>
              <th className={styles.center}>
                <MetricTooltip term="vs_local" showIcon>
                  {t("analytics.standings.colVsLocal")}
                </MetricTooltip>
              </th>
              <th className={styles.center}>
                <MetricTooltip term="confidence" showIcon>
                  {t("analytics.standings.colConfidence")}
                </MetricTooltip>
              </th>
              <th className={styles.center}>
                <MetricTooltip term="shift" showIcon>
                  {t("analytics.standings.colManual")}
                </MetricTooltip>
              </th>
              <th>{t("analytics.standings.colFlags")}</th>
            </tr>
          </thead>
          <tbody>
            {players.map((player) => {
              const isHighPoints = player.points >= 1;
              const isLowPoints = player.points <= -1;
              const performance = performanceByPlayer.get(player.id);

              return (
                <tr key={player.id}>
                  <td>
                    <div className="flex items-center gap-2">
                      <PlayerRoleIcon role={player.role} size={18} />
                      <span className="text-muted-foreground">{player.role}</span>
                    </div>
                  </td>
                  <td>
                    <div className="min-w-0">
                      <div className="truncate font-medium" title={player.name}>
                        {player.name}
                      </div>
                      {player.is_newcomer || player.is_newcomer_role ? (
                        <div className="mt-1">
                          <AnomalyChip
                            label={
                              player.is_newcomer
                                ? t("analytics.triage.newPlayer")
                                : t("analytics.triage.newRole")
                            }
                          />
                        </div>
                      ) : null}
                    </div>
                  </td>
                  <td className={styles.center}>
                    <DivisionBadge division={player.division} tournamentGrid={tournamentGrid} />
                  </td>
                  <td className={styles.center}>
                    <DivisionMove player={player} tournamentGrid={tournamentGrid} />
                  </td>
                  <td className={styles.center}>{formatAnalyticsNumber(player.move_2)}</td>
                  <td className={styles.center}>{formatAnalyticsNumber(player.move_1)}</td>
                  <td
                    className={cn(
                      styles.center,
                      "font-semibold tabular-nums",
                      isHighPoints && styles.pointsHigh,
                      isLowPoints && styles.pointsLow
                    )}
                  >
                    {player.points > 0 ? "+" : ""}
                    {formatAnalyticsNumber(player.points)}
                  </td>
                  <td className={styles.center}>
                    {performance ? (
                      <span className="inline-flex items-center justify-center gap-1">
                        {formatAnalyticsNumber(performance.impact_score, 0)}
                        {/* No algorithmId: SHAP explanations are produced by the
                            Performance ML v2 algorithm, not the selected shift
                            algorithm, so the latest explanation is the right one. */}
                        <ExplanationPopover
                          playerId={player.id}
                          tournamentId={player.tournament_id}
                        />
                      </span>
                    ) : (
                      "-"
                    )}
                  </td>
                  <td className={styles.center}>
                    {performance ? (
                      <span title={`Local percentile ${formatAnalyticsNumber(performance.local_percentile, 0)} / n=${performance.local_reference_n}`}>
                        {performance.local_zscore > 0 ? "+" : ""}
                        {formatAnalyticsNumber(performance.local_zscore, 2)}
                      </span>
                    ) : (
                      "-"
                    )}
                  </td>
                  <td className={styles.center}>{formatConfidencePercent(player.confidence)}</td>
                  <td className={styles.center}>
                    {canEdit ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 px-2 tabular-nums"
                        onClick={() => setEditingPlayer(player)}
                        title={t("analytics.standings.editManualShift")}
                      >
                        {formatAnalyticsNumber(player.shift)}
                      </Button>
                    ) : (
                      <span className="tabular-nums">{formatAnalyticsNumber(player.shift)}</span>
                    )}
                  </td>
                  <td>
                    <div className={styles.chips}>
                      {player.anomalies.map((anomaly, index) => (
                        <AnomalyChip key={`${player.id}-${anomaly.kind}-${index}`} anomaly={anomaly} />
                      ))}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {editingPlayer ? (
        <ChangeDivisionModal
          player={editingPlayer}
          open={editingPlayer != null}
          setOpen={(open) => {
            if (!open) setEditingPlayer(null);
          }}
        />
      ) : null}
    </div>
  );
};

const RoleLane = ({ team }: { team: TeamAnalytics }) => {
  const tournamentGrid = team.tournament?.division_grid_version;
  const players = useMemo(() => sortTeamPlayers(team.players), [team.players]);

  return (
    <div className={styles.roleLane}>
      {players.map((player) => (
        <div
          key={player.id}
          className={cn(
            styles.roleCell,
            (player.is_newcomer || player.is_newcomer_role) && styles.roleCellNew,
            player.anomalies.length > 0 && styles.roleCellAnomaly
          )}
          title={player.name}
        >
          <PlayerRoleIcon role={player.role} size={14} />
          <DivisionBadge division={player.division} tournamentGrid={tournamentGrid} size={22} />
          <span className={styles.roleName}>{player.name.split("#")[0]}</span>
        </div>
      ))}
    </div>
  );
};

const CONFIDENCE_TONE_CLASS: Record<"high" | "medium" | "low", string> = {
  high: "text-emerald-300",
  medium: "text-amber-300",
  low: "text-muted-foreground"
};

const TeamRow = ({
  team,
  open,
  onToggle,
  performanceByPlayer,
  distribution
}: {
  team: TeamAnalytics;
  open: boolean;
  onToggle: () => void;
  performanceByPlayer: Map<number, PerformanceV2>;
  distribution?: StandingsDistribution;
}) => {
  const { t } = useTranslation();
  const groupName = team.group?.name ?? "-";
  const conf = confidenceWord(team.avg_confidence);
  const shiftDirection =
    team.total_shift > 0 ? "promote" : team.total_shift < 0 ? "demote" : "flat";
  const groupClass = groupName === "A"
    ? styles.groupA
    : groupName === "B"
      ? styles.groupB
      : groupName === "C"
        ? styles.groupC
        : groupName === "D"
          ? styles.groupD
          : undefined;
  const placementDelta = team.placement_delta;
  const deltaClass = placementDelta == null
    ? undefined
    : placementDelta > 0
      ? styles.deltaUp
      : placementDelta < 0
        ? styles.deltaDown
        : undefined;

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onToggle();
    }
  };

  return (
    <div className={styles.teamRow} id={team.id.toString()}>
      <div
        className={styles.teamRowMain}
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={onToggle}
        onKeyDown={onKeyDown}
      >
        <span className={cn(styles.groupBand, groupClass)} />
        <div className={styles.placement}>
          <div className={styles.placementNum}>{team.placement ?? "-"}</div>
          <div className={cn(styles.placementDelta, deltaClass)}>
            {placementDelta == null ? "-" : placementDelta > 0 ? `+${placementDelta}` : placementDelta}
          </div>
        </div>
        <div className={styles.teamName}>
          <div className={styles.teamTitle} title={team.name}>
            {team.name}
          </div>
          <div className={styles.teamMeta}>
            <span>{t("common.group")} {groupName}</span>
            {distribution ? (
              <span
                title={`Monte Carlo: mean ${distribution.mean_position.toFixed(1)}, P(top1) ${(distribution.prob_top1 * 100).toFixed(0)}%`}
              >
                {t("analytics.standings.predictedRange", {
                  mean: distribution.mean_position.toFixed(1),
                  p10: distribution.p10_position.toFixed(0),
                  p90: distribution.p90_position.toFixed(0)
                })}
              </span>
            ) : (
              <span>{t("analytics.standings.predicted", { place: team.predicted_place ?? "-" })}</span>
            )}
          </div>
        </div>
        <RoleLane team={team} />
        <div className={styles.record}>
          <span className={styles.wins}>{team.wins}</span>
          <span className="mx-1 text-muted-foreground">/</span>
          <span className={styles.losses}>{team.losses}</span>
          <div className="text-[11px] text-muted-foreground">{t("analytics.standings.record")}</div>
        </div>
        <div className={styles.confidence}>
          <div className={styles.confidenceText}>
            <MetricTooltip term="confidence" focusable={false}>
              <span className="text-muted-foreground">{t("analytics.standings.confidence")}</span>
            </MetricTooltip>
            <br />
            <span
              className={cn("font-semibold", CONFIDENCE_TONE_CLASS[conf.tone])}
              title={formatConfidencePercent(team.avg_confidence)}
            >
              {t(`analytics.confidence.${conf.tone}`)}
            </span>
          </div>
        </div>
        <div className={styles.shiftCell}>
          <ForecastChip
            direction={shiftDirection}
            magnitude={Math.abs(team.total_shift)}
            focusable={false}
            rawTooltip={`Balancer ${formatAnalyticsNumber(team.balancer_shift, 1)} · manual ${formatAnalyticsNumber(team.manual_shift, 1)}`}
          />
        </div>
        <div className={styles.chips}>
          {team.anomalies.slice(0, 2).map((anomaly, index) => (
            <AnomalyChip key={`${team.id}-${anomaly.kind}-${index}`} anomaly={anomaly} />
          ))}
          {team.manual_shift_points !== 0 ? (
            <AnomalyChip label={t("analytics.standings.manual")} />
          ) : null}
        </div>
        <ChevronRight
          className={cn(styles.chevron, open && styles.chevronOpen)}
          size={18}
          aria-hidden="true"
        />
      </div>
      {open ? <TeamDetail team={team} performanceByPlayer={performanceByPlayer} /> : null}
    </div>
  );
};

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
      (left, right) => Math.abs(right.total_shift) - Math.abs(left.total_shift) || left.name.localeCompare(right.name)
    );
  }

  return [...teams].sort(
    (left, right) =>
      (left.placement ?? Number.MAX_SAFE_INTEGER) -
        (right.placement ?? Number.MAX_SAFE_INTEGER) ||
      left.name.localeCompare(right.name)
  );
};

const AnalyticsStandings = ({ teams, performanceByPlayer, distributionByTeam }: AnalyticsStandingsProps) => {
  const { t } = useTranslation();
  const [mode, setMode] = useState<SortMode>("standings");
  const [expandedId, setExpandedId] = useState<number | null>(teams[0]?.id ?? null);
  const visibleTeams = useMemo(() => sortedTeams(teams, mode), [teams, mode]);
  const modeLabel: Record<SortMode, string> = {
    standings: t("analytics.standings.sortStandings"),
    predicted: t("analytics.standings.sortPredicted"),
    shift: t("analytics.standings.sortShift")
  };

  return (
    <Card className="overflow-hidden">
      <div className={styles.sectionHead}>
        <div>
          <div className={styles.sectionTitle}>{t("analytics.standings.title")}</div>
          <div className={styles.sectionSub}>
            {t("analytics.standings.sortedBy", { count: teams.length, mode: modeLabel[mode] })}
          </div>
        </div>
        <div className={styles.sectionTabs} aria-label={t("analytics.standings.title")}>
          <button
            type="button"
            className={cn(styles.sectionTab, mode === "standings" && styles.sectionTabActive)}
            onClick={() => setMode("standings")}
          >
            {modeLabel.standings}
          </button>
          <button
            type="button"
            className={cn(styles.sectionTab, mode === "predicted" && styles.sectionTabActive)}
            onClick={() => setMode("predicted")}
          >
            {modeLabel.predicted}
          </button>
          <button
            type="button"
            className={cn(styles.sectionTab, mode === "shift" && styles.sectionTabActive)}
            onClick={() => setMode("shift")}
          >
            {modeLabel.shift}
          </button>
        </div>
      </div>
      <div className={styles.teamGrid}>
        {visibleTeams.map((team) => (
          <TeamRow
            key={team.id}
            team={team}
            open={expandedId === team.id}
            onToggle={() => setExpandedId((current) => current === team.id ? null : team.id)}
            performanceByPlayer={performanceByPlayer}
            distribution={distributionByTeam?.get(team.id)}
          />
        ))}
      </div>
    </Card>
  );
};

export default AnalyticsStandings;
