"use client";

import { Crown } from "lucide-react";
import { useTranslations } from "next-intl";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { HeroCoord } from "@/components/site/PageHero";
import { TournamentTeamCardFrame } from "@/components/TournamentTeamCard";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/division-grid";
import { getRoleIconName } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { DraftPick, DraftPlayer, DraftRole, DraftTeam } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { buildRosterByTeam, rosterRankForPlayer, rosterRoleForPlayer } from "../_lib/draft-workspace-model";

const ROSTER_ROLES: DraftRole[] = ["tank", "dps", "support"];

interface TeamRostersProps {
  teams: DraftTeam[];
  players: DraftPlayer[];
  picks: DraftPick[];
  teamSize: number;
  myTeamId?: number | null;
  focusTeamOnly?: boolean;
  onClockTeamId?: number | null;
  divisionGrid: DivisionGrid;
}

export function TeamRosters({
  teams,
  players,
  picks,
  teamSize,
  myTeamId = null,
  focusTeamOnly = false,
  onClockTeamId = null,
  divisionGrid
}: TeamRostersProps) {
  const t = useTranslations("draftRedesign");
  const rosters = buildRosterByTeam(players);
  const visibleTeams =
    focusTeamOnly && myTeamId != null
      ? teams.filter((team) => team.id === myTeamId)
      : [...teams].sort((left, right) => left.draft_position - right.draft_position);

  return (
    <section aria-labelledby="team-rosters-heading">
      <div className="border-b border-[color:var(--aqt-border)] pb-3">
        <HeroCoord>{t("rosterCoordinate")}</HeroCoord>
        <h2 id="team-rosters-heading" className="mt-1 font-onest text-lg font-semibold">
          {focusTeamOnly ? t("myTeam") : t("teamRosters")}
        </h2>
      </div>
      <div
        className={cn(
          "mt-4 grid gap-4",
          focusTeamOnly ? "grid-cols-1" : "md:grid-cols-2 xl:grid-cols-3"
        )}
      >
        {visibleTeams.map((team) => {
          const roster = rosters.get(team.id) ?? [];
          const onClock = team.id === onClockTeamId;
          const rosterRoles = roster.map((player) => rosterRoleForPlayer(player, picks));
          // ponytail: role-target = ceil(team_size/3) default; upgrade to real targets if the session exposes them
          const roleTarget = Math.ceil(teamSize / 3);
          const rankValues = roster
            .map((player) => player.rank_value)
            .filter((value): value is number => value != null);
          const avgRank =
            rankValues.length > 0
              ? rankValues.reduce((sum, value) => sum + value, 0) / rankValues.length
              : null;
          const avgDivision = avgRank == null ? null : resolveDivisionFromRank(divisionGrid, avgRank);
          const openSlots = Math.max(0, teamSize - roster.length);

          return (
            <TournamentTeamCardFrame
              key={team.id}
              name={team.name}
              positionTag={<span className="placement def">#{team.draft_position}</span>}
              className={cn(
                "min-w-0",
                onClock && "ring-2 ring-[color:var(--aqt-teal)] ring-offset-2 ring-offset-[color:var(--aqt-bg)]"
              )}
              style={team.id === myTeamId ? { borderColor: "var(--aqt-teal)" } : undefined}
              metricLabel={avgDivision != null ? t("teamAverage") : undefined}
              metricValue={
                avgDivision != null ? (
                  <span title={`${getDivisionLabel(divisionGrid, avgDivision)} · ${avgRank!.toFixed(0)} SR`}>
                    <PlayerDivisionIcon
                      division={avgDivision}
                      width={24}
                      height={24}
                      className="h-6 w-6 object-contain"
                      tournamentGrid={divisionGrid}
                    />
                  </span>
                ) : undefined
              }
            >
              {onClock && (
                <p className="px-4 pt-2 text-xs font-semibold uppercase tracking-wide text-[color:var(--aqt-teal)]">
                  {t("onTheClock")}
                </p>
              )}
              <div className="flex flex-wrap gap-3 px-4 pt-2 text-xs text-[color:var(--aqt-fg-muted)]">
                {ROSTER_ROLES.map((role) => {
                  const filled = rosterRoles.filter((r) => r === role).length;
                  return (
                    <span key={role} className="inline-flex items-center gap-1">
                      <PlayerRoleIcon role={getRoleIconName(role)} size={14} />
                      {filled}/{roleTarget}
                    </span>
                  );
                })}
              </div>
              {roster.length > 0 || openSlots > 0 ? (
                <div className="roster-scroll">
                  <table className="roster">
                    <thead>
                      <tr>
                        <th className="c" style={{ width: 48 }}>
                          {t("role")}
                        </th>
                        <th>{t("sortName")}</th>
                        <th className="c" style={{ width: 68 }}>
                          {t("rank")}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {roster.map((player) => {
                        const role = rosterRoleForPlayer(player, picks);
                        const rank = rosterRankForPlayer(player, role);
                        const division = player.division_number ?? resolveDivisionFromRank(divisionGrid, rank);
                        const divisionLabel =
                          division == null ? null : getDivisionLabel(divisionGrid, division);
                        return (
                          <tr key={player.id}>
                            <td className="c">
                              <span
                                className="inline-flex h-8 w-8 items-center justify-center"
                                title={t(`roles.${role}`)}
                              >
                                {player.is_captain ? (
                                  <Crown className="h-4 w-4 text-[color:var(--aqt-warm)]" />
                                ) : (
                                  <PlayerRoleIcon role={getRoleIconName(role)} size={16} />
                                )}
                              </span>
                            </td>
                            <td>
                              <span className="block max-w-[16rem] truncate font-medium">
                                {player.battle_tag ?? `#${player.id}`}
                              </span>
                            </td>
                            <td className="c">
                              {division != null ? (
                                <span
                                  className="inline-flex rounded-md px-1 py-0.5"
                                  title={[divisionLabel, rank != null ? `${rank} SR` : null]
                                    .filter(Boolean)
                                    .join(" · ")}
                                >
                                  <PlayerDivisionIcon
                                    division={division}
                                    width={32}
                                    height={32}
                                    className="h-8 w-8 object-contain drop-shadow-[0_3px_8px_rgba(0,0,0,0.35)]"
                                    tournamentGrid={divisionGrid}
                                  />
                                </span>
                              ) : (
                                <span className="text-[color:var(--aqt-fg-faint)]">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                      {Array.from({ length: openSlots }, (_, index) => (
                        <tr key={`open-${index}`} className="opacity-50">
                          <td className="c">
                            <span className="inline-flex h-8 w-8 items-center justify-center">—</span>
                          </td>
                          <td>
                            <span className="block max-w-[16rem] truncate text-[color:var(--aqt-fg-faint)]">
                              {t("openSlot")} {roster.length + index + 1}
                            </span>
                          </td>
                          <td className="c">
                            <span className="text-[color:var(--aqt-fg-faint)]">—</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="px-4 py-6 text-sm text-[color:var(--aqt-fg-muted)]">
                  {t("emptyRoster")}
                </p>
              )}
            </TournamentTeamCardFrame>
          );
        })}
      </div>
    </section>
  );
}
