"use client";

import { Crown } from "lucide-react";
import { useTranslations } from "next-intl";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { HeroCoord } from "@/components/site/PageHero";
import { TournamentTeamCardFrame } from "@/components/TournamentTeamCard";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/division-grid";
import { getRoleIconName } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { DraftPlayer, DraftRole, DraftTeam } from "@/types/draft.types";

import { buildRosterByTeam } from "../_lib/draft-workspace-model";

interface TeamRostersProps {
  teams: DraftTeam[];
  players: DraftPlayer[];
  myTeamId?: number | null;
  focusTeamOnly?: boolean;
}

export function TeamRosters({
  teams,
  players,
  myTeamId = null,
  focusTeamOnly = false
}: TeamRostersProps) {
  const t = useTranslations("draftRedesign");
  const divisionGrid = useDivisionGrid();
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
          return (
            <TournamentTeamCardFrame
              key={team.id}
              name={team.name}
              positionTag={<span className="placement def">#{team.draft_position}</span>}
              className="min-w-0"
              style={team.id === myTeamId ? { borderColor: "var(--aqt-teal)" } : undefined}
            >
              {roster.length > 0 ? (
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
                        const division =
                          player.division_number ??
                          resolveDivisionFromRank(divisionGrid, player.rank_value);
                        const divisionLabel =
                          division == null ? null : getDivisionLabel(divisionGrid, division);
                        return (
                          <tr key={player.id}>
                            <td className="c">
                              <span
                                className="inline-flex h-8 w-8 items-center justify-center"
                                title={t(`roles.${player.primary_role}`)}
                              >
                                {player.is_captain ? (
                                  <Crown className="h-4 w-4 text-[color:var(--aqt-warm)]" />
                                ) : (
                                  <PlayerRoleIcon
                                    role={getRoleIconName(player.primary_role as DraftRole)}
                                    size={16}
                                  />
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
                                  title={[
                                    divisionLabel,
                                    player.rank_value != null ? `${player.rank_value} SR` : null
                                  ]
                                    .filter(Boolean)
                                    .join(" · ")}
                                >
                                  <PlayerDivisionIcon
                                    division={division}
                                    width={32}
                                    height={32}
                                    className="h-8 w-8 object-contain drop-shadow-[0_3px_8px_rgba(0,0,0,0.35)]"
                                  />
                                </span>
                              ) : (
                                <span className="text-[color:var(--aqt-fg-faint)]">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
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
