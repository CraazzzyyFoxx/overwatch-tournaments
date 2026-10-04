"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";

import { usePermissions } from "@/hooks/usePermissions";
import { tabFallback, useHubEncountersQuery } from "../../hubQueries";
import { MatchesView } from "../MatchesView";

const TournamentLogsTab = dynamic(
  () =>
    import("../../components/TournamentLogsTab").then((module) => ({
      default: module.TournamentLogsTab
    })),
  { loading: () => tabFallback }
);

export default function LogsViewPage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const { canAccessPermission } = usePermissions();
  const encountersQuery = useHubEncountersQuery(tournamentId);

  return (
    <MatchesView tournamentId={tournamentId}>
      {({ workspaceId }) => (
        <TournamentLogsTab
          tournamentId={tournamentId}
          workspaceId={workspaceId}
          encounters={encountersQuery.data?.results ?? []}
          canUploadLogs={canAccessPermission("match.update", workspaceId)}
        />
      )}
    </MatchesView>
  );
}
