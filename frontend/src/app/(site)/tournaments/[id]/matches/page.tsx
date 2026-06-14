"use client";

import { useParams, useSearchParams } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";

import TournamentEncountersPage from "@/app/(site)/tournaments/[id]/pages/TournamentEncountersPage";

import { useTournamentQuery } from "../_hooks/useTournamentClientData";

function MatchesPageSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-9 w-64 rounded-lg" />
      <Skeleton className="h-80 w-full rounded-xl" />
    </div>
  );
}

export default function TournamentMatchesPage() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const tournamentId = Number(params.id);
  const tournamentQuery = useTournamentQuery(tournamentId);

  const page = Number.parseInt(searchParams.get("page") ?? "1", 10) || 1;
  const search = searchParams.get("search") ?? "";

  if (tournamentQuery.isLoading) {
    return <MatchesPageSkeleton />;
  }

  if (!tournamentQuery.data) {
    return (
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-8 text-center text-muted-foreground">
        Tournament not found.
      </div>
    );
  }

  return (
    <TournamentEncountersPage
      tournament={tournamentQuery.data}
      page={page}
      search={search}
    />
  );
}
