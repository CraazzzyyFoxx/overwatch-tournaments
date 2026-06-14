"use client";

import { Tournament } from "@/types/tournament.types";
import EncountersTable from "@/components/EncountersTable";

export interface TournamentEncounterPageProps {
  tournament: Tournament;
  page: number;
  search: string;
}

const TournamentEncountersPage = ({
  tournament,
  page,
  search
}: TournamentEncounterPageProps) => {
  return (
    <EncountersTable
      InitialPage={page}
      search={search}
      hideTournament={true}
      tournamentId={tournament.id}
      workspaceId={tournament.workspace_id}
    />
  );
};

export default TournamentEncountersPage;
