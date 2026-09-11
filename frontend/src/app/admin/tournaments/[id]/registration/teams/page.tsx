"use client";

import { useParams } from "next/navigation";

import { RegistrationTeamsBrowser } from "../../components/RegistrationTeamsBrowser";
import { tabFallback, useHubTournamentQuery } from "../../hubQueries";

/**
 * The teams captains registered, organizer side.
 *
 * Its own section rather than a switcher inside `entries`: the layout only
 * offers it when `team_formation` is `registration`, which is also the only
 * case where the read returns anything.
 */
export default function RegistrationTeamsPage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const validTournamentId =
    Number.isFinite(tournamentId) && tournamentId > 0 ? tournamentId : null;

  // Already in cache — the shell runs the same query under the same key.
  const { data: tournament, isLoading } = useHubTournamentQuery(tournamentId);
  const workspaceId = tournament?.workspace_id ?? null;

  if (isLoading) return tabFallback;
  if (validTournamentId == null || workspaceId == null) return null;

  return <RegistrationTeamsBrowser tournamentId={validTournamentId} workspaceId={workspaceId} />;
}
