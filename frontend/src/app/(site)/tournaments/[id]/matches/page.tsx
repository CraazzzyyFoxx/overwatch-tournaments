"use client";

import { useParams, useSearchParams } from "next/navigation";

import TournamentEncountersPage from "@/app/(site)/tournaments/[id]/pages/TournamentEncountersPage";

export default function TournamentMatchesPage() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const page = Number.parseInt(searchParams.get("page") ?? "1", 10) || 1;
  const search = searchParams.get("search") ?? "";

  return (
    <TournamentEncountersPage
      key={params.id}
      tournamentId={Number(params.id)}
      page={page}
      search={search}
    />
  );
}
