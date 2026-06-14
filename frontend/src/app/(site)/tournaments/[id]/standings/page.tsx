"use client";

import { useParams } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";

import TournamentStandingsPage from "@/app/(site)/tournaments/[id]/pages/TournamentStandingsPage";

import { useTournamentQuery } from "../_hooks/useTournamentClientData";

function StandingsPageSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-48 w-full rounded-xl" />
      <Skeleton className="h-48 w-full rounded-xl" />
    </div>
  );
}

export default function TournamentStandingsRoutePage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const tournamentQuery = useTournamentQuery(tournamentId);

  if (tournamentQuery.isLoading) {
    return <StandingsPageSkeleton />;
  }

  if (!tournamentQuery.data) {
    return (
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-8 text-center text-muted-foreground">
        Tournament not found.
      </div>
    );
  }

  return <TournamentStandingsPage tournament={tournamentQuery.data} />;
}
