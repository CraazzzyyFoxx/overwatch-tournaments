"use client";

import { Crown } from "lucide-react";
import { useTranslations } from "next-intl";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { TournamentTeamCardFrame } from "@/components/TournamentTeamCard";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/division-grid";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { DraftPick, DraftPlayer, DraftRole, DraftTeam } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { teamCrest } from "../_lib/draft-crest";
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
  /** Vertical compact card list (mockup `.teams-col`) vs the default grid of full team cards. */
  variant?: "grid" | "column";
  /** Auth user ids of captains currently connected, for the column card's captain dot. */
  onlineCaptainIds?: Set<number>;
}

interface TeamRosterView {
  roster: DraftPlayer[];
  roleFillCounts: Record<DraftRole, number>;
  roleTarget: number;
  avgRank: number | null;
  avgDivision: number | null;
  openSlots: number;
}

function computeTeamRosterView(
  team: DraftTeam,
  rosters: Map<number, DraftPlayer[]>,
  picks: DraftPick[],
  teamSize: number,
  divisionGrid: DivisionGrid
): TeamRosterView {
  const roster = [...(rosters.get(team.id) ?? [])].sort(
    (a, b) =>
      ROSTER_ROLES.indexOf(rosterRoleForPlayer(a, picks)) -
      ROSTER_ROLES.indexOf(rosterRoleForPlayer(b, picks))
  );
  const rosterRoles = roster.map((player) => rosterRoleForPlayer(player, picks));
  // ponytail: role-target = ceil(team_size/3) default; upgrade to real targets if the session exposes them
  const roleTarget = Math.ceil(teamSize / 3);
  const roleFillCounts = Object.fromEntries(
    ROSTER_ROLES.map((role) => [role, rosterRoles.filter((r) => r === role).length])
  ) as Record<DraftRole, number>;
  const rankValues = roster
    .map((player) => player.rank_value)
    .filter((value): value is number => value != null);
  const avgRank =
    rankValues.length > 0 ? rankValues.reduce((sum, value) => sum + value, 0) / rankValues.length : null;
  const avgDivision = avgRank == null ? null : resolveDivisionFromRank(divisionGrid, avgRank);
  const openSlots = Math.max(0, teamSize - roster.length);
  return { roster, roleFillCounts, roleTarget, avgRank, avgDivision, openSlots };
}

export function TeamRosters({
  teams,
  players,
  picks,
  teamSize,
  myTeamId = null,
  focusTeamOnly = false,
  onClockTeamId = null,
  divisionGrid,
  variant = "grid",
  onlineCaptainIds
}: TeamRostersProps) {
  const t = useTranslations("draftRedesign");
  const rosters = buildRosterByTeam(players);

  if (variant === "column") {
    const columnTeams = [...teams].sort((left, right) => left.draft_position - right.draft_position);
    return (
      <section aria-labelledby="team-rosters-column-heading">
        <div className="border-b border-[color:var(--aqt-border)] pb-3">
          <h2 id="team-rosters-column-heading" className="font-onest text-lg font-semibold">
            {t("teamRosters")}
          </h2>
        </div>
        <div className="mt-4 flex flex-col gap-3 overflow-y-auto">
          {columnTeams.map((team) => {
            const view = computeTeamRosterView(team, rosters, picks, teamSize, divisionGrid);
            const onClock = team.id === onClockTeamId;
            const isMine = team.id === myTeamId;
            const crest = teamCrest(team);
            const captainOnline =
              team.captain_auth_user_id != null && (onlineCaptainIds?.has(team.captain_auth_user_id) ?? false);

            return (
              <div
                key={team.id}
                className={cn(
                  "min-w-0 overflow-hidden rounded-[14px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]",
                  isMine && "border-[color:var(--aqt-teal)]/60",
                  onClock && "ring-1 ring-[color:var(--aqt-teal)] shadow-[0_0_22px_color-mix(in_srgb,var(--aqt-teal)_20%,transparent)]"
                )}
              >
                {onClock && (
                  <p className="px-3 pt-2 font-mono text-[9px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-teal)]">
                    {t("onTheClock")}
                  </p>
                )}
                <div className="flex items-center gap-2.5 border-b border-[color:var(--aqt-border)] px-3 py-2.5">
                  <span
                    className="grid h-[30px] w-[30px] shrink-0 place-items-center rounded-[9px] text-[13px] font-extrabold"
                    style={{ background: `hsl(${crest.hue} 55% 22%)`, color: `hsl(${crest.hue} 70% 72%)` }}
                  >
                    {crest.initial}
                  </span>
                  <span className="min-w-0 truncate text-[15px] font-semibold tracking-tight">{team.name}</span>
                  <span
                    className="h-[7px] w-[7px] shrink-0 rounded-full"
                    style={
                      captainOnline
                        ? { background: "var(--aqt-support)", boxShadow: "0 0 5px var(--aqt-support)" }
                        : { background: "var(--aqt-fg-faint)" }
                    }
                    title={captainOnline ? t("captainOnline") : t("captainOffline")}
                  />
                  <span className="ml-auto flex shrink-0 items-center gap-2">
                    {view.avgDivision != null && (
                      <span
                        title={`${getDivisionLabel(divisionGrid, view.avgDivision)} · ${view.avgRank!.toFixed(0)} SR`}
                      >
                        <PlayerDivisionIcon
                          division={view.avgDivision}
                          width={24}
                          height={24}
                          className="h-6 w-6 object-contain"
                          tournamentGrid={divisionGrid}
                        />
                      </span>
                    )}
                    <span className="font-mono text-xs text-[color:var(--aqt-fg-faint)]">
                      #{team.draft_position}
                    </span>
                  </span>
                </div>
                <div className="flex gap-4 border-b border-[color:var(--aqt-border)] px-3 py-2 font-mono text-xs text-[color:var(--aqt-fg-muted)]">
                  {ROSTER_ROLES.map((role) => (
                    <span key={role} className="inline-flex items-center gap-1" style={{ color: ROLE_ACCENT[role] }}>
                      <PlayerRoleIcon role={getRoleIconName(role)} size={14} color={ROLE_ACCENT[role]} />
                      {view.roleFillCounts[role]}/{view.roleTarget}
                    </span>
                  ))}
                </div>
                <div className="divide-y divide-[color:var(--aqt-border)]">
                  {view.roster.map((player) => {
                    const role = rosterRoleForPlayer(player, picks);
                    const rank = rosterRankForPlayer(player, role);
                    const division = player.division_number ?? resolveDivisionFromRank(divisionGrid, rank);
                    const divisionLabel = division == null ? null : getDivisionLabel(divisionGrid, division);
                    return (
                      <div
                        key={player.id}
                        className="grid grid-cols-[24px_1fr_auto] items-center gap-2 px-3 py-2 text-sm"
                      >
                        <span className="inline-flex h-6 w-6 items-center justify-center" title={t(`roles.${role}`)}>
                          {player.is_captain ? (
                            <Crown className="h-4 w-4 text-[color:var(--aqt-warm)]" />
                          ) : (
                            <PlayerRoleIcon role={getRoleIconName(role)} size={16} />
                          )}
                        </span>
                        <span className="min-w-0 truncate font-medium">{player.battle_tag ?? `#${player.id}`}</span>
                        {division != null ? (
                          <span title={[divisionLabel, rank != null ? `${rank} SR` : null].filter(Boolean).join(" · ")}>
                            <PlayerDivisionIcon
                              division={division}
                              width={26}
                              height={26}
                              className="h-[26px] w-[26px] object-contain"
                              tournamentGrid={divisionGrid}
                            />
                          </span>
                        ) : (
                          <span className="text-[color:var(--aqt-fg-faint)]">—</span>
                        )}
                      </div>
                    );
                  })}
                  {Array.from({ length: view.openSlots }, (_, index) => (
                    <div
                      key={`open-${index}`}
                      className="grid grid-cols-[24px_1fr_auto] items-center gap-2 px-3 py-2 text-sm opacity-40"
                    >
                      <span className="inline-flex h-6 w-6 items-center justify-center text-[color:var(--aqt-fg-faint)]">
                        ·
                      </span>
                      <span className="min-w-0 truncate italic text-[color:var(--aqt-fg-faint)]">
                        {t("openSlot")} {view.roster.length + index + 1}
                      </span>
                      <span className="text-[color:var(--aqt-fg-faint)]">—</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    );
  }

  const visibleTeams =
    focusTeamOnly && myTeamId != null
      ? teams.filter((team) => team.id === myTeamId)
      : [...teams].sort((left, right) => left.draft_position - right.draft_position);

  return (
    <section aria-labelledby="team-rosters-heading">
      <div className="border-b border-[color:var(--aqt-border)] pb-3">
        <h2 id="team-rosters-heading" className="font-onest text-lg font-semibold">
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
          const view = computeTeamRosterView(team, rosters, picks, teamSize, divisionGrid);
          const { roster, roleTarget, avgRank, avgDivision, openSlots } = view;
          const onClock = team.id === onClockTeamId;

          return (
            <TournamentTeamCardFrame
              key={team.id}
              name={team.name}
              className={cn(
                "min-w-0",
                onClock && "ring-2 ring-[color:var(--aqt-teal)] ring-offset-2 ring-offset-[color:var(--aqt-bg)]"
              )}
              style={team.id === myTeamId ? { borderColor: "var(--aqt-teal)" } : undefined}
              metricValue={
                avgDivision != null ? (
                  <span title={`${getDivisionLabel(divisionGrid, avgDivision)} · ${avgRank!.toFixed(0)} SR`}>
                    <PlayerDivisionIcon
                      division={avgDivision}
                      width={26}
                      height={26}
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
                  const filled = view.roleFillCounts[role];
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
