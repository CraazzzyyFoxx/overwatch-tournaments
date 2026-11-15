"use client";

import { useTranslations } from "next-intl";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { PermissionGate } from "@/components/admin/PermissionGate";
import { TeamsBrowser } from "@/components/admin/teams/list/TeamsBrowser";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { GameScopeGate } from "@/components/workspace/GameScopeGate";
import { useGameScope } from "@/hooks/useGameScope";
import { usePermissions } from "@/hooks/usePermissions";
import { useWorkspaceStore } from "@/stores/workspace.store";

/** Every roster of the workspace: a multi page (spec §6.9) — every game's teams, or the game its Game chip filters. */
export default function TeamsPage() {
  const t = useTranslations("adminPeople.teams");
  const { canAccessPermission, isLoaded } = usePermissions();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const scope = useGameScope({ axis: workspaceId ?? "all" });

  return (
    <PermissionGate
      loaded={isLoaded}
      allowed={canAccessPermission("team.read", workspaceId)}
      description={t("noPermission")}
    >
      <div className="space-y-4">
        <AdminPageHeader title={t("title")} />
        {workspaceId === null ? (
          // The rosters are the workspace's: a first visit learns its community after mounting, and reads nothing before.
          <Skeleton className="h-64 w-full rounded-xl" />
        ) : (
          <GameScopeGate scope={scope}>
            {(game) => <TeamsBrowser workspaceId={workspaceId} discipline={game} games={scope.games} />}
          </GameScopeGate>
        )}
      </div>
    </PermissionGate>
  );
}
