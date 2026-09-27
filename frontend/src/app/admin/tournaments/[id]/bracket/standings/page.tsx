"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";

import { tabFallback } from "../../hubQueries";
import { MatchesView } from "../../matches/MatchesView";

const StandingsBrowser = dynamic(
  () =>
    import("@/components/admin/StandingsBrowser").then((module) => ({
      default: module.StandingsBrowser
    })),
  { loading: () => tabFallback }
);

export default function StandingsViewPage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);

  return (
    <MatchesView tournamentId={tournamentId}>
      {({ workspaceId }) => (
        <StandingsBrowser tournamentId={tournamentId} workspaceId={workspaceId} />
      )}
    </MatchesView>
  );
}
