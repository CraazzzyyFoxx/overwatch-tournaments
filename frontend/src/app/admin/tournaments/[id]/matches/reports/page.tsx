"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";

import { usePermissions } from "@/hooks/usePermissions";
import { tabFallback } from "../../hubQueries";
import { MatchesView } from "../MatchesView";

const EncounterReportsBrowser = dynamic(
  () =>
    import("@/components/admin/EncounterReportsBrowser").then((module) => ({
      default: module.EncounterReportsBrowser
    })),
  { loading: () => tabFallback }
);

export default function ReportsViewPage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const { canAccessPermission } = usePermissions();

  return (
    <MatchesView tournamentId={tournamentId}>
      {({ workspaceId, tournamentName }) => (
        <EncounterReportsBrowser
          tournamentId={tournamentId}
          workspaceId={workspaceId}
          tournamentName={tournamentName}
          canUpdateEncounter={canAccessPermission("match.result", workspaceId)}
        />
      )}
    </MatchesView>
  );
}
