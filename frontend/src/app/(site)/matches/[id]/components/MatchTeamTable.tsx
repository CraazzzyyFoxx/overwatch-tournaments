"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { PlayerWithStats, TeamWithStats } from "@/types/team.types";
import { LogStatsName } from "@/types/stats.types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { sortTeamPlayers } from "@/utils/player";
import PlayerName from "@/components/PlayerName";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { PerformanceBadge } from "@/components/PerformanceBagde";
import DivisionIcon from "@/components/DivisionIcon";
import { HeroStrip } from "@/components/hero/HeroImage";
import type { DivisionGridVersion } from "@/types/workspace.types";
import {
  STAT_META,
  GROUP_COLOR,
  formatStat,
  playerStat,
  activePlayers
} from "@/utils/matchStats";

interface MatchTeamTableProps {
  team: TeamWithStats;
  isHome: boolean;
  matchRound: number;
  /** Dynamic stat columns to render (from the active preset). */
  columns: LogStatsName[];
  /** Per-column max across both teams — scales the inline magnitude bars. */
  columnMax: Record<string, number>;
  tournamentGrid?: DivisionGridVersion | null;
}

const StatCell = ({
  name,
  value,
  max
}: {
  name: LogStatsName;
  value: number;
  max: number;
}) => {
  const meta = STAT_META[name];
  const showBar = Boolean(meta?.bar) && max > 0;
  const pct = showBar ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const color = meta ? GROUP_COLOR[meta.group] : "var(--aqt-teal)";

  return (
    <div className="flex flex-col items-center gap-1">
      <span className="aqt-tnum text-[13px] text-[color:var(--aqt-fg)]">{formatStat(name, value)}</span>
      {showBar ? (
        <div className="h-[3px] w-full max-w-[64px] overflow-hidden rounded-full bg-[hsl(0_0%_100%/0.06)]">
          <div
            className="h-full rounded-full"
            style={{ width: `${pct}%`, background: color, opacity: 0.85 }}
          />
        </div>
      ) : null}
    </div>
  );
};

const MatchTeamTable = ({
  team,
  isHome,
  matchRound,
  columns,
  columnMax,
  tournamentGrid
}: MatchTeamTableProps) => {
  const t = useTranslations<never>();
  const teamAccent = isHome ? "var(--aqt-teal)" : "var(--aqt-rose)";

  const sortedPlayers = sortTeamPlayers(team.players);
  const activeIds = new Set(activePlayers(team, matchRound).map((player) => player.id));
  const players: PlayerWithStats[] = sortedPlayers.filter((player) => activeIds.has(player.id));

  return (
    <Table>
      <TableHeader>
        <TableRow style={{ backgroundColor: `color-mix(in srgb, ${teamAccent} 12%, transparent)` }}>
          <TableHead
            className="min-w-[220px] sticky left-0 z-5"
            style={{
              background: `linear-gradient(to right, color-mix(in srgb, ${teamAccent} 26%, var(--aqt-bg)), color-mix(in srgb, ${teamAccent} 12%, var(--aqt-bg)) 60%)`
            }}
          >
            {t("matches.teamLabel", { name: team.name })}
          </TableHead>
          <TableHead className="text-center">{t("matches.col.division")}</TableHead>
          <TableHead className="text-center">{t("common.heroes")}</TableHead>
          <TableHead className="text-center whitespace-nowrap">{t("matches.stats.rating")}</TableHead>
          {columns.map((name) => {
            const meta = STAT_META[name];
            return (
              <TableHead
                key={name}
                className="text-center whitespace-nowrap"
                title={meta ? t(meta.labelKey as Parameters<typeof t>[0]) : name}
              >
                {meta?.abbr ?? name}
              </TableHead>
            );
          })}
        </TableRow>
      </TableHeader>
      <TableBody>
        {players.map((player) => {
          const heroes = player.heroes[matchRound] ?? [];
          return (
            <TableRow key={player.id} className="hover:bg-[hsl(0_0%_100%/0.02)]">
              <TableCell
                className="flex flex-row items-center gap-2 min-w-[220px] sticky left-0 z-10"
                style={{
                  background: `linear-gradient(to right, color-mix(in srgb, ${teamAccent} 22%, var(--aqt-bg)), var(--aqt-bg) 60%)`
                }}
              >
                <PlayerRoleIcon role={player.role} />
                <PlayerName player={player} includeSpecialization={true} />
              </TableCell>
              <TableCell>
                <div className="flex justify-center">
                  <DivisionIcon division={player.division} width={32} height={32} tournamentGrid={tournamentGrid} />
                </div>
              </TableCell>
              <TableCell>
                <div className="flex justify-center">
                  <HeroStrip heroes={heroes} size="sm" limit={6} />
                </div>
              </TableCell>
              <TableCell className="text-center">
                <div className="flex flex-col items-center gap-1">
                  <span className="aqt-tnum text-[15px] font-bold leading-none text-[color:var(--aqt-teal)]">
                    {formatStat(LogStatsName.ImpactPoints, player.stats[matchRound]?.impact_points)}
                  </span>
                  <PerformanceBadge performance={player.stats[matchRound]?.performance} />
                </div>
              </TableCell>
              {columns.map((name) => (
                <TableCell key={name} className="text-center">
                  <StatCell name={name} value={playerStat(player, matchRound, name)} max={columnMax[name] ?? 0} />
                </TableCell>
              ))}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
};

export default MatchTeamTable;
