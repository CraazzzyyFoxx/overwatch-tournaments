import { useTranslations } from "next-intl";

import { TournamentTeamCardFrame, TournamentTeamTable } from "@/components/TournamentTeamCard";
import TeamName from "@/components/TeamName";
import type { Team } from "@/types/team.types";
import type { DivisionGridVersion } from "@/types/workspace.types";

/**
 * One side's roster for an encounter (encounter page, pre-game room, bracket
 * rosters modal): the Teams-page card without group and placement, with the
 * side's colour on top. `team` is null while the slot is still TBD.
 */
export default function EncounterRosterPanel({
  team,
  side,
  tournamentGrid
}: Readonly<{
  team: Team | null;
  side: "home" | "away";
  tournamentGrid?: DivisionGridVersion | null;
}>) {
  const t = useTranslations();

  return (
    <TournamentTeamCardFrame
      side={side}
      name={<TeamName team={team} fallback={t("common.tbd")} size="md" />}
      metricLabel={team ? t("teams.roster.avgSr") : undefined}
      metricValue={team ? <span className="tabular-nums">{team.avg_sr.toFixed(0)}</span> : undefined}
    >
      {team && team.players.length > 0 ? (
        <TournamentTeamTable
          players={team.players}
          tournamentGrid={tournamentGrid}
          captainUserId={team.captain_id}
        />
      ) : (
        <p className="px-3.5 py-3 text-sm text-[color:var(--aqt-fg-dim)]">{t("common.noData")}</p>
      )}
    </TournamentTeamCardFrame>
  );
}
