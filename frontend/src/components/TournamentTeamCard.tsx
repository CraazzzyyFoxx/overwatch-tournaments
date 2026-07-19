import React from "react";
import { sortTeamPlayers, type TeamRosterPlayer } from "@/utils/player";
import { CircleMinus, CirclePlus, CornerDownRight } from "lucide-react";
import PlayerName from "@/components/PlayerName";
import { Team } from "@/types/team.types";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Skeleton } from "@/components/ui/skeleton";
import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import { HeroStrip } from "@/components/hero/HeroImage";
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
  youLabel,
  avgMvpLabel,
  heroesLabel,
  signatureHeroesLabel
}: {
  players: TeamRosterPlayer[];
  tournamentGrid?: DivisionGridVersion | null;
  /** When a roster row belongs to this user id, it gets a "you" tag. */
  highlightUserId?: number;
  /** Localized label for the "you" tag (supplied by i18n-aware callers). */
  youLabel?: string;
  /** Localized header for the Avg MVP column (falls back to English). */
  avgMvpLabel?: string;
  /** Localized header for the Heroes column (falls back to English). */
  heroesLabel?: string;
  /** Localized title/aria for the signature-heroes strip (falls back to English). */
  signatureHeroesLabel?: string;
}) => {
  const sortedPlayers = sortTeamPlayers(players);

  // Only render the dossier columns when at least one row carries the data;
  // other callers (team cards) pass rosters without these fields and render
  // exactly as before.
  const showExtra = players.some((p) => p.avg_mvp != null || (p.heroes?.length ?? 0) > 0);
  const signatureTitle = signatureHeroesLabel ?? "Signature heroes";

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
            {showExtra ? (
              <>
                <th style={{ width: 64, textAlign: "right" }}>{avgMvpLabel ?? "Avg MVP"}</th>
                <th style={{ width: 100 }}>{heroesLabel ?? "Heroes"}</th>
              </>
            ) : null}
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
                <div className="flex items-center gap-2">
                  <PlayerName player={player} includeSpecialization={true} />
                  {youLabel && highlightUserId != null && player.user_id === highlightUserId ? (
                    <span
                      className="aqt-mono rounded-[4px] px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em]"
                      style={{
                        background: "hsl(172 70% 49% / 0.12)",
                        border: "1px solid hsl(172 70% 49% / 0.3)",
                        color: "var(--aqt-teal)"
                      }}
                    >
                      {youLabel}
                    </span>
                  ) : null}
                </div>
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
              {showExtra ? (
                <>
                  <td
                    className="aqt-mono"
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
  return (
    <TournamentTeamCardFrame
      id={team.id.toString()}
      name={team.name}
      leadingTag={
        team.group?.name ? (
          <span className={cn("group-chip", groupChipClass(team.group.name))}>
            Group {team.group.name}
          </span>
        ) : (
          <span />
        )
      }
      positionTag={
        team.placement != null ? (
          <span className={cn("placement", placementClass(team.placement))}>#{team.placement}</span>
        ) : null
      }
      metricLabel="Avg. SR"
      metricValue={team.avg_sr.toFixed(0)}
    >
      <TournamentTeamTable
        players={team.players}
        tournamentGrid={team.tournament?.division_grid_version}
      />
    </TournamentTeamCardFrame>
  );
};
