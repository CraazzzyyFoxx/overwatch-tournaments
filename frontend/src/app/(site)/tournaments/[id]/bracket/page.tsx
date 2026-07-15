"use client";

import { useParams } from "next/navigation";

import { useTournamentQuery } from "../_hooks/useTournamentClientData";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentBracketSkeleton } from "../_components/TournamentSkeletons";
import TournamentBracketPage from "./TournamentBracketPage";

export default function BracketPage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const tournamentQuery = useTournamentQuery(tournamentId);

  if (tournamentQuery.isPending && !tournamentQuery.data) {
    return <TournamentBracketSkeleton />;
  }

  if (!tournamentQuery.data) {
    return <TournamentPageState state="initial-error" onRetry={() => tournamentQuery.refetch()} />;
  }

  return <TournamentBracketPage tournament={tournamentQuery.data} />;
}
