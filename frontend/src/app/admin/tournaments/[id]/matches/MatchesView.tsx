"use client";

import type { ReactNode } from "react";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { usePermissions } from "@/hooks/usePermissions";
import { tabFallback, useHubTournamentQuery } from "../hubQueries";

export interface MatchesViewScope {
  workspaceId: number | null;
  tournamentName: string;
}

/**
 * The `match.read` gate the Matches views share — and the Bracket tab's
 * Standings and Lobbies views, which read the same match results.
 *
 * The gate lives here rather than in `layout.tsx` because the layout is
 * navigation: the sub-tab bar has no tournament of its own to authorize
 * against, and the pre-redesign version bounced an unpermitted visitor to a
 * sibling sub-tab that needed the very same grant — a redirect loop dressed as
 * a guard.
 *
 * The tournament comes from the hub's shared query, so this costs no request
 * beyond what the shell already holds.
 */
export function MatchesView({
  tournamentId,
  children
}: Readonly<{
  tournamentId: number;
  children: (scope: MatchesViewScope) => ReactNode;
}>) {
  const { canAccessPermission, isLoaded } = usePermissions();
  const tournamentQuery = useHubTournamentQuery(tournamentId);

  if (tournamentQuery.isLoading || !isLoaded) return tabFallback;

  const tournament = tournamentQuery.data;
  if (!tournament) return null;

  const workspaceId = tournament.workspace_id ?? null;
  if (!canAccessPermission("match.read", workspaceId)) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Unauthorized</CardTitle>
          <CardDescription>
            You do not have permission to read matches in this tournament.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return <>{children({ workspaceId, tournamentName: tournament.name })}</>;
}
