"use client";

import { useParams } from "next/navigation";

import { useTournamentQuery } from "../_hooks/useTournamentClientData";
import { DraftBoard } from "./_components/DraftBoard";

export default function TournamentDraftRoutePage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const tournamentQuery = useTournamentQuery(tournamentId);

  if (tournamentQuery.isLoading) {
    return (
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-8 text-center text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (!tournamentQuery.data) {
    return (
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-8 text-center text-muted-foreground">
        Tournament not found.
      </div>
    );
  }

  return <DraftBoard tournament={tournamentQuery.data} />;
}
