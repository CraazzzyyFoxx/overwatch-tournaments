"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";

import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { usePermissions } from "@/hooks/usePermissions";
import { tabFallback, useHubEncountersQuery, useHubTournamentQuery } from "../../hubQueries";
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
  // The shell's tournament read: only a game that parses an uploaded log file is offered the upload.
  const tournament = useHubTournamentQuery(tournamentId).data;
  const metadata = useDisciplineMetadata(tournament?.workspace_id ?? "all", tournament?.discipline ?? null);
  const fileUpload = metadata.data?.discipline.capabilities.log_upload === true;

  return (
    <MatchesView tournamentId={tournamentId}>
      {({ workspaceId }) => (
        <TournamentLogsTab
          tournamentId={tournamentId}
          workspaceId={workspaceId}
          encounters={encountersQuery.data?.results ?? []}
          canUploadLogs={fileUpload && canAccessPermission("match.update", workspaceId)}
        />
      )}
    </MatchesView>
  );
}
