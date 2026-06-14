import React from "react";
import { sortTeamPlayers, type TeamRosterPlayer } from "@/utils/player";
import { CircleMinus, CirclePlus, CornerDownRight } from "lucide-react";
import PlayerName from "@/components/PlayerName";
import { Team } from "@/types/team.types";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Skeleton } from "@/components/ui/skeleton";
import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import { cn } from "@/lib/utils";
import type { DivisionGridVersion } from "@/types/workspace.types";

export const TournamentTeamCardSkeleton = () => {
  return <Skeleton className="h-[380px] w-full rounded-xl" />;
};

function NewMark({ active }: { active: boolean }) {
  return (
    <div className="flex justify-center">
      {active ? (
        <CirclePlus className="h-5 w-5" style={{ color: "hsl(0 80% 65%)" }} />
      ) : (
        <CircleMinus className="h-5 w-5 text-white/30" />
      )}
    </div>
  );
}

export const TournamentTeamTable = ({
  players,
  tournamentGrid,
}: {
  players: TeamRosterPlayer[];
  tournamentGrid?: DivisionGridVersion | null;
}) => {
  const sortedPlayers = sortTeamPlayers(players);

  return (
    <div className="roster-scroll">
      <table className="roster">
        <thead>
          <tr>
            <th style={{ width: 48 }}>Role</th>
            <th>Battle tag</th>
            <th className="c" style={{ width: 60 }}>
              Div
            </th>
            <th className="c" style={{ width: 48 }}>
              New
            </th>
            <th className="c" style={{ width: 48 }}>
              Role
            </th>
          </tr>
        </thead>
        <tbody>
          {sortedPlayers.map((player) => (
            <tr key={player.id}>
              <td>
                {player.is_substitution ? (
                  <CornerDownRight className="ml-1.5 h-4 w-4 text-white/40" />
                ) : (
                  <PlayerRoleIcon role={player.role} />
                )}
              </td>
              <td>
                <PlayerName player={player} includeSpecialization={true} />
              </td>
              <td className="c">
                <div className="flex justify-center">
                  <PlayerDivisionIcon
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

export const TournamentTeamCard = ({ team }: { team: Team }) => {
  return (
    <article id={team.id.toString()} className="team-card">
      <header className="tc-header">
        <div className="tc-tags">
          {team.group?.name ? (
            <span className={cn("group-chip", groupChipClass(team.group.name))}>
              Group {team.group.name}
            </span>
          ) : (
            <span />
          )}
          {team.placement != null && (
            <span className={cn("placement", placementClass(team.placement))}>
              #{team.placement}
            </span>
          )}
        </div>

        <div className="tc-name-row">
          <h3 className="tc-name">{team.name}</h3>
          <div className="tc-sr">
            <div className="l">Avg. SR</div>
            <div className="v">{team.avg_sr.toFixed(0)}</div>
          </div>
        </div>
      </header>

      <div className="tc-divider" />

      <TournamentTeamTable
        players={team.players}
        tournamentGrid={team.tournament?.division_grid_version}
      />
    </article>
  );
};
