"use client";

import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { PlayerWithStats, TeamWithStats } from "@/types/team.types";
import { LogStatsName } from "@/types/stats.types";
import { TableBody, TableCell, TableHead, TableRow } from "@/components/ui/table";
import { sortTeamPlayers } from "@/lib/player";
import PlayerName from "@/components/PlayerName";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { PerformanceBadge } from "@/components/PerformanceBadge";
import DivisionIcon from "@/components/DivisionIcon";
import { HeroStrip } from "@/components/hero/HeroImage";
import { TeamLogo } from "@/components/TeamName";
import type { DivisionGridVersion } from "@/types/workspace.types";
import {
  STAT_META,
  GROUP_COLOR,
  formatStat,
  playerStat,
  activePlayers,
  resolveMatchMvpPlacement
} from "@/lib/match-stats";

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
  const format = useFormatter();
  const meta = STAT_META[name];
  const showBar = Boolean(meta?.bar) && max > 0;
  const pct = showBar ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const color = meta ? GROUP_COLOR[meta.group] : "var(--aqt-teal)";

  return (
    <div className="flex flex-col items-center gap-1">
      <span className="aqt-tnum text-caption text-[color:var(--aqt-fg)]">{formatStat(name, value, format)}</span>
      {showBar ? (
        <div className="h-[3px] w-full max-w-[64px] overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)]">
          <div
            className="h-full rounded-full"
            style={{ width: `${pct}%`, background: color, opacity: 0.85 }}
          />
        </div>
      ) : null}
    </div>
  );
};

/**
 * One team's block of the scoreboard, rendered as a `<tbody>` so both teams can
 * live inside a single `<table>`. They used to be two sibling `<Table>`s, each
 * with its own horizontal scroll container: scrolling to a stat column on one
 * left the other behind, defeating the side-by-side comparison this panel is for.
 */
const MatchTeamTable = ({
  team,
  isHome,
  matchRound,
  columns,
  columnMax,
  tournamentGrid
}: MatchTeamTableProps) => {
  const t = useTranslations<never>();
  const format = useFormatter();
  const teamAccent = isHome ? "var(--aqt-teal)" : "var(--aqt-rose)";

  const sortedPlayers = sortTeamPlayers(team.players);
  const activeIds = new Set(activePlayers(team, matchRound).map((player) => player.id));
  const players: PlayerWithStats[] = sortedPlayers.filter((player) => activeIds.has(player.id));

  return (
    <TableBody className={isHome ? undefined : "border-t border-[color:var(--aqt-border)]"}>
      <TableRow style={{ backgroundColor: `color-mix(in srgb, ${teamAccent} 12%, transparent)` }}>
        <TableHead
          scope="col"
          className="min-w-[220px] sticky left-0 z-5"
          style={{
            background: `linear-gradient(to right, color-mix(in srgb, ${teamAccent} 26%, var(--aqt-card)), color-mix(in srgb, ${teamAccent} 12%, var(--aqt-card)) 60%)`
          }}
        >
          <span className="inline-flex items-center gap-2">
            <TeamLogo team={team} size="xs" />
            {t("matches.teamLabel", { name: team.name })}
          </span>
        </TableHead>
        <TableHead scope="col" className="text-center">
          {t("matches.col.division")}
        </TableHead>
        <TableHead scope="col" className="text-center">
          {t("common.heroes")}
        </TableHead>
        <TableHead scope="col" className="text-center whitespace-nowrap">
          {t("matches.stats.rating")}
        </TableHead>
        {columns.map((name) => {
          const meta = STAT_META[name];
          const fullLabel = meta ? t(meta.labelKey as Parameters<typeof t>[0]) : name;
          return (
            <TableHead
              key={name}
              scope="col"
              className="text-center whitespace-nowrap"
              // The visible text is an abbreviation ("E", "K/D"); assistive
              // technology gets the spelled-out column name instead.
              aria-label={fullLabel}
              title={fullLabel}
            >
              {meta?.abbr ?? name}
            </TableHead>
          );
        })}
      </TableRow>
      {players.map((player) => {
        const heroes = player.heroes[matchRound] ?? [];
        return (
          <TableRow key={player.id} className="hover:bg-[color:var(--aqt-overlay-1)]">
            <TableCell
              className="flex flex-row items-center gap-2 min-w-[220px] sticky left-0 z-10"
              style={{
                background: `linear-gradient(to right, color-mix(in srgb, ${teamAccent} 22%, var(--aqt-card)), var(--aqt-card) 60%)`
              }}
            >
              <PlayerRoleIcon role={player.role} />
              <PlayerName player={player} includeSpecialization={true} />
            </TableCell>
            <TableCell>
              <div className="flex justify-center">
                <DivisionIcon
                  division={player.division}
                  width={32}
                  height={32}
                  tournamentGrid={tournamentGrid}
                />
              </div>
            </TableCell>
            <TableCell>
              <div className="flex justify-center">
                <HeroStrip heroes={heroes} size="sm" limit={6} />
              </div>
            </TableCell>
            <TableCell className="text-center">
              <div className="flex flex-col items-center gap-1">
                <span className="aqt-tnum text-ui font-bold leading-none text-[color:var(--aqt-teal)]">
                  {formatStat(LogStatsName.ImpactPoints, player.stats[matchRound]?.impact_points, format)}
                </span>
                <PerformanceBadge performance={resolveMatchMvpPlacement(player, matchRound)} />
              </div>
            </TableCell>
            {columns.map((name) => (
              <TableCell key={name} className="text-center">
                <StatCell
                  name={name}
                  value={playerStat(player, matchRound, name)}
                  max={columnMax[name] ?? 0}
                />
              </TableCell>
            ))}
          </TableRow>
        );
      })}
    </TableBody>
  );
};

export default MatchTeamTable;
