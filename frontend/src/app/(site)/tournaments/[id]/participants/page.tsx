"use client";

import { useParams } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";

import TournamentParticipantsPage from "@/app/(site)/tournaments/[id]/pages/TournamentParticipantsPage";

import { useTournamentQuery } from "../_hooks/useTournamentClientData";

function ParticipantsPageSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-10 w-full rounded-lg" />
      <Skeleton className="h-80 w-full rounded-xl" />
    </div>
  );
}

export default function TournamentParticipantsRoutePage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const tournamentQuery = useTournamentQuery(tournamentId);

  if (tournamentQuery.isLoading) {
    return <ParticipantsPageSkeleton />;
  }

  if (!tournamentQuery.data) {
    return (
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-8 text-center text-muted-foreground">
        Tournament not found.
      </div>
    );
  }

  return <TournamentParticipantsPage tournament={tournamentQuery.data} />;
}
