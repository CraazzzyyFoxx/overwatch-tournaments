"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import workspaceService from "@/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

import { DraftEditor } from "../../editor/DraftEditor";
import { bandsFromTiers } from "../../editor/draftReducer";
import { divisionGridQueryKeys } from "@/lib/divisions/query-keys";

/**
 * The draft editor route (F12): loads a version, its parent and its readiness,
 * then hands them to `DraftEditor`.
 *
 * The split is deliberate. `DraftEditor` holds a reducer seeded from the
 * version's tiers, so "the version changed under it" has to mean "mount a new
 * editor" — otherwise a save would leave the old snapshot stack pointing at
 * tiers that no longer exist. This component owns that remount (`epoch`), and
 * both saving and discarding local edits go through it.
 */
export default function DivisionDraftEditorPage() {
  const params = useParams<{ versionId: string }>();
  const versionId = Number(params.versionId);
  const [epoch, setEpoch] = useState(0);

  const { isSuperuser, canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const getCurrentWorkspace = useWorkspaceStore((state) => state.getCurrentWorkspace);
  const activeVersionId = getCurrentWorkspace()?.default_division_grid_version_id ?? null;

  const canRead =
    workspaceId !== null && (isSuperuser || canAccessPermission("division_grid.read", workspaceId));
  const canUpdate =
    workspaceId !== null &&
    (isSuperuser || canAccessPermission("division_grid.update", workspaceId));
  const canDelete =
    workspaceId !== null &&
    (isSuperuser || canAccessPermission("division_grid.delete", workspaceId));

  const versionQuery = useQuery({
    queryKey: divisionGridQueryKeys.version(versionId),
    queryFn: () => workspaceService.getDivisionGridVersion(versionId),
    enabled: canRead && Number.isFinite(versionId)
  });
  const version = versionQuery.data ?? null;

  const parentQuery = useQuery({
    queryKey: divisionGridQueryKeys.version(version?.created_from_version_id ?? null),
    queryFn: () => workspaceService.getDivisionGridVersion(version!.created_from_version_id!),
    enabled: canRead && version?.created_from_version_id != null
  });

  const readinessQuery = useQuery({
    queryKey: divisionGridQueryKeys.readiness(workspaceId, versionId),
    queryFn: () => workspaceService.getDivisionGridVersionReadiness(workspaceId!, versionId),
    enabled: canRead && Number.isFinite(versionId)
  });

  if (workspaceId === null) {
    return (
      <PageStateCard
        state="empty"
        title="No workspace selected"
        description="Pick a workspace to open its division grid draft."
      />
    );
  }

  if (!canRead) {
    return (
      <PageStateCard
        state="not-found"
        title="This draft is not available to you"
        description="Reading the division grid needs the division_grid.read permission in this workspace."
      />
    );
  }

  if (versionQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title="Version could not be loaded"
        description="The draft failed to load, so nothing here can be edited safely."
        actionLabel="Retry"
        onAction={() => void versionQuery.refetch()}
      />
    );
  }

  // The parent has to be in hand BEFORE the editor mounts: `DraftEditor` seeds
  // its reducer from these props once, so a base that arrives a render later
  // would leave the Changes view comparing the draft against nothing.
  const awaitingParent =
    version?.created_from_version_id !== null && version !== null && parentQuery.isPending;
  if (versionQuery.isLoading || !version || awaitingParent) {
    return <Skeleton className="h-[32rem] w-full rounded-xl" />;
  }

  return (
    <DraftEditor
      key={`${version.id}:${epoch}`}
      workspaceId={workspaceId}
      version={version}
      base={parentQuery.data ? bandsFromTiers(parentQuery.data.tiers) : []}
      baseLabel={parentQuery.data ? `v${parentQuery.data.version}` : "the base version"}
      readiness={readinessQuery.data ?? null}
      activeVersionId={activeVersionId}
      editable={version.status === "draft" && canUpdate}
      canPublish={canUpdate}
      canDelete={canDelete}
      onReload={() => setEpoch((current) => current + 1)}
    />
  );
}
