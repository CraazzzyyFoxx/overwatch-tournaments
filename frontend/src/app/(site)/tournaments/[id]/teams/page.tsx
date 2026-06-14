"use client";

import { useParams } from "next/navigation";

import TournamentTeamsPage, {
  TournamentTeamsPageSkeleton,
} from "@/app/(site)/tournaments/[id]/pages/TournamentTeamsPage";

import { useTournamentQuery } from "../_hooks/useTournamentClientData";

export default function TournamentTeamsRoutePage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const tournamentQuery = useTournamentQuery(tournamentId);

  if (tournamentQuery.isLoading) {
    return <TournamentTeamsPageSkeleton />;
  }

  if (!tournamentQuery.data) {
    return (
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-8 text-center text-muted-foreground">
        Tournament not found.
      </div>
    );
  }

  return <TournamentTeamsPage tournament={tournamentQuery.data} />;
}
