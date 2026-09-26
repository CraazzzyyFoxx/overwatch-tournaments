"use client";

// The card's own global CSS (`.team-card`, `.roster`, `.group-chip`,
// `.placement`), moved out of globals.css and next to its only consumer.
import "./TournamentTeamCard.css";

import React from "react";
import { useTranslations } from "next-intl";
import { sortTeamPlayers, type TeamRosterPlayer } from "@/utils/player";
import { CircleMinus, CirclePlus, CornerDownRight, Crown } from "lucide-react";
import PlayerName from "@/components/PlayerName";
import { Team } from "@/types/team.types";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import DivisionIcon from "@/components/DivisionIcon";
import { HeroStrip } from "@/components/hero/HeroImage";
import TeamName from "@/components/TeamName";
import { cn } from "@/lib/utils";
import type { DivisionGridVersion } from "@/types/workspace.types";

function NewMark({ active }: Readonly<{ active: boolean }>) {
  return (
    <div className="flex justify-center">
      {active ? (
        <CirclePlus className="h-5 w-5 text-[color:var(--aqt-rose)]" />
      ) : (
        <CircleMinus className="h-5 w-5 text-[color:var(--aqt-fg-faint)]" />
      )}
    </div>
  );
}

/** Threshold color for the average MVP placement (1 = best). */
function avgMvpColor(value: number): string {
  if (value <= 2.5) return "var(--aqt-emerald)";
  if (value >= 4.5) return "var(--aqt-fg-dim)";
  return "var(--aqt-fg)";
}

export const TournamentTeamTable = ({
  players,
  tournamentGrid,
  highlightUserId,
  captainUserId
}: {
  players: TeamRosterPlayer[];
  tournamentGrid?: DivisionGridVersion | null;
  /** When a roster row belongs to this user id, it gets a "you" tag. */
  highlightUserId?: number;
  /** When a roster row belongs to this user id, it gets a captain crown. */
  captainUserId?: number;
}) => {
  const t = useTranslations();
  const sortedPlayers = sortTeamPlayers(players);

  // Only render the dossier columns when at least one row carries the data;
  // other callers (team cards) pass rosters without these fields and render
  // exactly as before.
  const showExtra = players.some((p) => p.avg_mvp != null || (p.heroes?.length ?? 0) > 0);
  const signatureTitle = t("users.tournaments.roster.signatureHeroes");

  return (
    <div className="roster-scroll">
      <table className="roster">
        <thead>
          <tr>
            <th scope="col" style={{ width: 48 }}>
              {t("teams.roster.role")}
            </th>
            <th scope="col">{t("teams.roster.battleTag")}</th>
            <th scope="col" className="c" style={{ width: 60 }}>
              {t("teams.roster.division")}
            </th>
            <th scope="col" className="c" style={{ width: 48 }}>
              {t("teams.roster.newcomer")}
            </th>
            <th scope="col" className="c" style={{ width: 48 }}>
              {t("teams.roster.newcomerRole")}
            </th>
            {showExtra ? (
              <>
                <th scope="col" style={{ width: 64, textAlign: "right" }}>
                  {t("users.tournaments.roster.avgMvp")}
                </th>
                <th scope="col" style={{ width: 100 }}>
                  {t("users.tournaments.roster.heroes")}
                </th>
              </>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {sortedPlayers.map((player) => (
            <tr key={player.id}>
              <td>
                {player.is_substitution ? (
                  <CornerDownRight className="ml-1.5 h-4 w-4 text-[color:var(--aqt-fg-dim)]" />
                ) : (
                  <PlayerRoleIcon role={player.role} />
                )}
              </td>
              <td>
                <div className="flex items-center gap-2">
                  <PlayerName player={player} includeSpecialization={true} />
                  {captainUserId != null && player.user_id === captainUserId ? (
                    <span
                      className="inline-flex shrink-0 items-center text-[color:var(--aqt-amber)]"
                      title={t("registrationTeams.member.captain")}
                    >
                      <Crown className="size-3.5" aria-hidden />
                      <span className="sr-only">{t("registrationTeams.member.captain")}</span>
                    </span>
                  ) : null}
                  {highlightUserId != null && player.user_id === highlightUserId ? (
                    <span
                      className="aqt-tnum rounded-[4px] px-1.5 py-0.5 text-label font-bold uppercase tracking-label"
                      style={{
                        background: "color-mix(in srgb, var(--aqt-teal) 12%, transparent)",
                        border: "1px solid color-mix(in srgb, var(--aqt-teal) 30%, transparent)",
                        color: "var(--aqt-teal)"
                      }}
                    >
                      {t("users.tournaments.you")}
                    </span>
                  ) : null}
                </div>
              </td>
              <td className="c">
                <div className="flex justify-center">
                  <DivisionIcon
                    division={player.division}
                    width={32}
                    height={32}
                    tournamentGrid={tournamentGrid}
                  />
                </div>
              </td>
              <td className="c">
                <NewMark active={player.is_newcomer} />
              </td>
              <td className="c">
                <NewMark active={player.is_newcomer_role} />
              </td>
              {showExtra ? (
                <>
                  <td
                    className="aqt-tnum tabular-nums"
                    style={{
                      textAlign: "right",
                      color:
                        player.avg_mvp != null ? avgMvpColor(player.avg_mvp) : "var(--aqt-fg-dim)"
                    }}
                  >
                    {player.avg_mvp != null ? player.avg_mvp.toFixed(1) : "—"}
                  </td>
                  <td>
                    {player.heroes && player.heroes.length > 0 ? (
                      <div title={signatureTitle} aria-label={signatureTitle}>
                        <HeroStrip heroes={player.heroes} size="sm" limit={3} />
                      </div>
                    ) : (
                      <span className="text-[color:var(--aqt-fg-dim)]">—</span>
                    )}
                  </td>
                </>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

function groupChipClass(name?: string | null): string {
  switch (name?.trim().toUpperCase()) {
    case "B":
      return "b";
    case "C":
      return "c";
    case "D":
      return "d";
    default:
      return "a";
  }
}

function placementClass(placement: number): string {
  if (placement === 1) return "gold";
  if (placement === 2) return "silver";
  if (placement === 3) return "bronze";
  return "def";
}

interface TournamentTeamCardFrameProps extends React.HTMLAttributes<HTMLElement> {
  name: React.ReactNode;
  leadingTag?: React.ReactNode;
  positionTag?: React.ReactNode;
  metricLabel?: React.ReactNode;
  metricValue?: React.ReactNode;
}

/** Shared team-card chrome used by tournament tables and live draft rosters. */
export const TournamentTeamCardFrame = ({
  name,
  leadingTag,
  positionTag,
  metricLabel,
  metricValue,
  children,
  className,
  ...props
}: TournamentTeamCardFrameProps) => {
  const hasTags = leadingTag != null || positionTag != null;
  const hasMetric = metricLabel != null || metricValue != null;

  return (
    <article className={cn("team-card", className)} {...props}>
      <header className="tc-header">
        {hasTags && (
          <div className="tc-tags">
            {leadingTag ?? <span />}
            {positionTag}
          </div>
        )}
        <div className="tc-name-row">
          <h3 className="tc-name">{name}</h3>
          {hasMetric && (
            <div className="tc-sr">
              {metricLabel != null && <div className="l">{metricLabel}</div>}
              {metricValue != null && <div className="v">{metricValue}</div>}
            </div>
          )}
        </div>
      </header>
      <div className="tc-divider" />
      {children}
    </article>
  );
};

export const TournamentTeamCard = ({ team }: { team: Team }) => {
  const t = useTranslations();

  return (
    <TournamentTeamCardFrame
      id={team.id.toString()}
      name={<TeamName team={team} size="md" />}
      leadingTag={
        team.group?.name ? (
          <span className={cn("group-chip", groupChipClass(team.group.name))}>
            {t("teams.groupLabel", { name: team.group.name })}
          </span>
        ) : (
          <span />
        )
      }
      positionTag={
        team.placement != null ? (
          <span className={cn("placement tabular-nums", placementClass(team.placement))}>
            #{team.placement}
          </span>
        ) : null
      }
      metricLabel={t("teams.roster.avgSr")}
      metricValue={<span className="tabular-nums">{team.avg_sr.toFixed(0)}</span>}
    >
      <TournamentTeamTable
        players={team.players}
        tournamentGrid={team.tournament?.division_grid_version}
        captainUserId={team.captain_id}
      />
    </TournamentTeamCardFrame>
  );
};
