"use client";

import { TournamentParticipantsSkeleton } from "../_components/TournamentSkeletons";
import { TournamentPageState } from "../_components/TournamentPageState";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { FinishedParticipantsView } from "./_components/FinishedParticipantsView";
import { TournamentParticipantsView } from "./_components/TournamentParticipantsView";
import { overviewVariant } from "./tournamentOverview.model";

/**
 * Resolves the shared tournament overview so the route file stays a one-line
 * delegation, matching every other tournament sub-route. The overview is
 * already primed by the layout, so this is a cache read in practice — the
 * guards below only fire if that layout contract ever changes.
 *
 * Until the tournament is over the participants ARE the registrations; once it
 * is, the page shows who went where in the draft and how it paid off.
 */
export default function TournamentParticipantsPage({ slug }: Readonly<{ slug: string }>) {
  // Keyed by `slug`: shares TournamentClientLayout's overview cache entry.
  const tournamentQuery = useTournamentQuery(slug);

  if (!tournamentQuery.data) {
    if (tournamentQuery.isError) {
      return (
        <TournamentPageState state="initial-error" onRetry={() => void tournamentQuery.refetch()} />
      );
    }
    return <TournamentParticipantsSkeleton />;
  }
  if (overviewVariant(tournamentQuery.data.status) === "completed") {
    return <FinishedParticipantsView tournament={tournamentQuery.data} />;
  }
  return <TournamentParticipantsView tournament={tournamentQuery.data} />;
}
