"use client";

import React from "react";
import { AlertTriangle, ArrowDown, ArrowUp, CheckCircle2, Minus, Sparkles, Target } from "lucide-react";

import { PlayerAnalytics, TeamAnalytics } from "@/types/analytics.types";
import type { DivisionGridVersion } from "@/types/workspace.types";
import { Card } from "@/components/ui/card";
import DivisionIcon from "@/components/DivisionIcon";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import { isAnomalyGlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import MetricTooltip from "@/app/(site)/tournaments/analytics/components/MetricTooltip";
import AnomalyLegend from "@/app/(site)/tournaments/analytics/components/AnomalyLegend";

interface AttentionTriageProps {
  teams: TeamAnalytics[];
}

const DIVERGENCE_THRESHOLD = 4;
const GROUP_LIMIT = 6;

type PlayerWithTeam = PlayerAnalytics & {
  teamId: number;
  teamName: string;
  grid?: DivisionGridVersion | null;
};

/** Jump to the team's row in the standings board below. */
function TeamLink({ id, children }: { id: number; children: React.ReactNode }) {
  return (
    <a href={`#${id}`} className="truncate font-medium transition-colors hover:text-foreground">
      {children}
    </a>
  );
}

/** Classic DivisionGrid current → predicted move. */
function DivisionMoveMini({
  from,
  to,
  direction,
  grid,
}: {
  from: number | null;
  to: number | null;
  direction: PlayerAnalytics["predicted_direction"];
  grid?: DivisionGridVersion | null;
}) {
  const Arrow = direction === "promote" ? ArrowUp : direction === "demote" ? ArrowDown : Minus;
  const arrowCls =
    direction === "promote"
      ? "text-emerald-400"
      : direction === "demote"
        ? "text-rose-400"
        : "text-muted-foreground";

  return (
    <span className="inline-flex shrink-0 items-center gap-1">
      {from != null ? (
        <DivisionIcon division={from} tournamentGrid={grid} width={22} height={22} />
      ) : (
        <span className="text-muted-foreground">–</span>
      )}
      <Arrow className={cn("h-3.5 w-3.5", arrowCls)} aria-hidden="true" />
      {to != null ? (
        <DivisionIcon
          division={to}
          tournamentGrid={grid}
          width={22}
          height={22}
          className={cn("inline-block", direction === "flat" && "opacity-45")}
        />
      ) : (
        <span className="text-muted-foreground">–</span>
      )}
    </span>
  );
}

function GroupCard({
  title,
  icon,
  count,
  tone,
  action,
  children,
}: {
  title: React.ReactNode;
  icon: React.ReactNode;
  count: number;
  tone: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-card/40 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className={cn("flex h-6 w-6 items-center justify-center rounded-md", tone)}>{icon}</span>
        <span className="text-[13px] font-semibold text-foreground">{title}</span>
        {action}
        <span className="ml-auto rounded-full bg-muted/60 px-1.5 text-[11px] font-bold tabular-nums text-muted-foreground">
          {count}
        </span>
      </div>
      <div className="space-y-1.5 text-[13px] text-muted-foreground">{children}</div>
    </div>
  );
}

export default function AttentionTriage({ teams }: AttentionTriageProps) {
  const { t } = useTranslation();

  const players: PlayerWithTeam[] = teams.flatMap((team) =>
    team.players.map((player) => ({
      ...player,
      teamId: team.id,
      teamName: team.name,
      grid: team.tournament?.division_grid_version ?? null,
    })),
  );
  const playerById = new Map<number, PlayerWithTeam>(players.map((player) => [player.id, player]));

  const flags = teams.flatMap((team) =>
    team.anomalies.map((anomaly) => ({
      ...anomaly,
      teamId: team.id,
      player: playerById.get(anomaly.player_id),
    })),
  );

  const forecastMisses = [...teams]
    .filter(
      (team) =>
        team.placement_delta != null && Math.abs(team.placement_delta) >= DIVERGENCE_THRESHOLD,
    )
    .sort((a, b) => Math.abs(b.placement_delta ?? 0) - Math.abs(a.placement_delta ?? 0))
    .slice(0, GROUP_LIMIT);

  const bigMoves = players
    .filter((player) => player.predicted_direction !== "flat")
    .sort((a, b) => Math.abs(b.predicted_delta) - Math.abs(a.predicted_delta))
    .slice(0, GROUP_LIMIT);

  const newcomers = players
    .filter((player) => player.is_newcomer || player.is_newcomer_role)
    .slice(0, GROUP_LIMIT);

  const nothing =
    flags.length === 0 &&
    forecastMisses.length === 0 &&
    bigMoves.length === 0 &&
    newcomers.length === 0;

  return (
    <Card className="overflow-hidden border-border/60">
      <div className="flex items-center gap-2 border-b border-border/60 px-5 py-3">
        <AlertTriangle className="h-4 w-4 text-amber-400" aria-hidden="true" />
        <h2 className="font-display text-[15px] font-bold uppercase tracking-[0.04em] text-foreground">
          {t("analytics.triage.title")}
        </h2>
      </div>

      {nothing ? (
        <div className="flex items-center gap-2 px-5 py-6 text-sm text-muted-foreground">
          <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-hidden="true" />
          {t("analytics.triage.allClear")}
        </div>
      ) : (
        <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
          {flags.length > 0 ? (
            <GroupCard
              title={t("analytics.triage.flags")}
              icon={<AlertTriangle className="h-3.5 w-3.5" />}
              tone="bg-amber-500/15 text-amber-300"
              count={flags.length}
              action={<AnomalyLegend />}
            >
              {flags.slice(0, GROUP_LIMIT).map((flag, index) => (
                <div
                  key={`${flag.player_id}-${flag.kind}-${index}`}
                  className="flex items-center justify-between gap-2"
                >
                  {isAnomalyGlossaryTerm(flag.kind) ? (
                    <MetricTooltip term={flag.kind} className="text-amber-200" />
                  ) : (
                    <span className="capitalize text-amber-200">{flag.kind}</span>
                  )}
                  <TeamLink id={flag.player?.teamId ?? flag.teamId}>
                    {flag.player?.name ?? `#${flag.player_id}`}
                  </TeamLink>
                </div>
              ))}
            </GroupCard>
          ) : null}

          {forecastMisses.length > 0 ? (
            <GroupCard
              title={<MetricTooltip term="forecast_miss">{t("analytics.triage.misses")}</MetricTooltip>}
              icon={<Target className="h-3.5 w-3.5" />}
              tone="bg-rose-500/15 text-rose-300"
              count={forecastMisses.length}
            >
              {forecastMisses.map((team) => (
                <div key={team.id} className="flex items-center justify-between gap-2">
                  <TeamLink id={team.id}>{team.name}</TeamLink>
                  <span className="shrink-0 tabular-nums">
                    {t("analytics.triage.forecastFinished", {
                      predicted: team.predicted_place ?? "–",
                      finished: team.placement ?? "–",
                    })}
                  </span>
                </div>
              ))}
            </GroupCard>
          ) : null}

          {bigMoves.length > 0 ? (
            <GroupCard
              title={t("analytics.triage.moves")}
              icon={<Sparkles className="h-3.5 w-3.5" />}
              tone="bg-sky-500/15 text-sky-300"
              count={bigMoves.length}
            >
              {bigMoves.map((player) => (
                <div key={`move-${player.id}`} className="flex items-center justify-between gap-2">
                  <TeamLink id={player.teamId}>{player.name}</TeamLink>
                  <DivisionMoveMini
                    from={player.division}
                    to={player.predicted_division ?? player.division}
                    direction={player.predicted_direction}
                    grid={player.grid}
                  />
                </div>
              ))}
            </GroupCard>
          ) : null}

          {newcomers.length > 0 ? (
            <GroupCard
              title={<MetricTooltip term="newcomer">{t("analytics.triage.newcomers")}</MetricTooltip>}
              icon={<Sparkles className="h-3.5 w-3.5" />}
              tone="bg-emerald-500/15 text-emerald-300"
              count={newcomers.length}
            >
              {newcomers.map((player) => (
                <div key={`new-${player.id}`} className="flex items-center justify-between gap-2">
                  <TeamLink id={player.teamId}>{player.name}</TeamLink>
                  <span className="shrink-0 text-xs">
                    {player.is_newcomer
                      ? t("analytics.triage.newPlayer")
                      : t("analytics.triage.newRole")}
                  </span>
                </div>
              ))}
            </GroupCard>
          ) : null}
        </div>
      )}
    </Card>
  );
}
