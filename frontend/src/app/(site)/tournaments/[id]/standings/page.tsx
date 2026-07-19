"use client";

import { useParams } from "next/navigation";

import TournamentStandingsPage from "@/app/(site)/tournaments/[id]/pages/TournamentStandingsPage";

export default function TournamentStandingsRoutePage() {
  const params = useParams<{ id: string }>();
  return <TournamentStandingsPage key={params.id} tournamentId={Number(params.id)} />;
}
