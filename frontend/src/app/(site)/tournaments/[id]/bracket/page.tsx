"use client";

import { useParams } from "next/navigation";

import { Skeleton } from "@/components/ui/skeleton";
import { useTournamentQuery, useTournamentStagesQuery } from "../_hooks/useTournamentClientData";
import TournamentBracketPage from "./TournamentBracketPage";

function BracketPageSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-12 w-full rounded-xl" />
      <Skeleton className="h-[520px] w-full rounded-xl" />
    </div>
  );
}

export default function BracketPage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const tournamentQuery = useTournamentQuery(tournamentId);
  const stagesQuery = useTournamentStagesQuery(tournamentId);

  if (tournamentQuery.isLoading || stagesQuery.isLoading) {
    return <BracketPageSkeleton />;
  }

  if (!tournamentQuery.data) {
    return (
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-8 text-center text-muted-foreground">
        Tournament not found.
      </div>
    );
  }

  return (
    <TournamentBracketPage
      tournament={tournamentQuery.data}
      stages={stagesQuery.data ?? []}
    />
  );
}
