"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { useWorkspaceRead } from "@/hooks/useCurrentWorkspace";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { usePermissions } from "@/hooks/usePermissions";
import { activeGridVersionId } from "@/lib/divisions/grid";
import workspaceService from "@/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

import type { MappingChoices } from "../../editor/autoMap";
import { DraftEditor } from "../../editor/DraftEditor";
import { bandsFromTiers, createLadder } from "../../editor/draftReducer";
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
  const t = useTranslations("adminSettings.divisions");
  const params = useParams<{ versionId: string }>();
  const versionId = Number(params.versionId);
  const [epoch, setEpoch] = useState(0);
  const [carriedChoices, setCarriedChoices] = useState<MappingChoices>({});

  const { isSuperuser, canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const workspace = useWorkspaceRead(workspaceId);

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
  const gridsQuery = useQuery({
    queryKey: divisionGridQueryKeys.grids(workspaceId),
    queryFn: () => workspaceService.getDivisionGrids(workspaceId!),
    enabled: canRead
  });
  const grid = gridsQuery.data?.find((candidate) => candidate.id === version?.grid_id);
  // The version's own game, served by the version read — never the browsing choice or the current default.
  const discipline =
    version?.discipline ??
    grid?.discipline ??
    Object.entries(workspace?.effective_division_grid_versions ?? {}).find(
      ([, effective]) => effective.grid_id === version?.grid_id
    )?.[0] ??
    null;
  const activeVersionId = activeGridVersionId(workspace, discipline);
  const metadataQuery = useDisciplineMetadata(workspaceId ?? "all", discipline);
  const metadata = metadataQuery.data;
  // A declared native ladder that carries no ranks is invalid metadata, not "no ladder": the editor
  // would otherwise drop every stored native link on save.
  const ladder = useMemo(
    () => (metadata?.discipline.capabilities.native_ladder ? createLadder(metadata.native_ladder) : null),
    [metadata]
  );
  const metadataInvalid =
    metadata !== undefined && metadata.discipline.capabilities.native_ladder && ladder === null;

  const parentQuery = useQuery({
    queryKey: divisionGridQueryKeys.version(version?.created_from_version_id ?? null),
    queryFn: () => workspaceService.getDivisionGridVersion(version!.created_from_version_id!),
    enabled: canRead && version?.created_from_version_id != null
  });

  const readinessQuery = useQuery({
    queryKey: divisionGridQueryKeys.readiness(workspaceId, discipline, versionId),
    queryFn: () => workspaceService.getDivisionGridVersionReadiness(workspaceId!, versionId),
    enabled: canRead && Number.isFinite(versionId)
  });

  if (workspaceId === null) {
    return (
      <PageStateCard
        state="empty"
        headingLevel={1}
        title={t("noWorkspace.title")}
        description={t("noWorkspace.openDraft")}
      />
    );
  }

  if (!canRead) {
    return (
      <PageStateCard
        state="not-found"
        headingLevel={1}
        title={t("draftUnavailable.title")}
        description={t("draftUnavailable.description")}
      />
    );
  }

  if (versionQuery.isError) {
    return (
      <PageStateCard
        state="error"
        headingLevel={1}
        title={t("versionLoadError.title")}
        description={t("versionLoadError.description")}
        actionLabel={t("retry")}
        onAction={() => void versionQuery.refetch()}
      />
    );
  }

  // The parent has to be in hand BEFORE the editor mounts: `DraftEditor` seeds
  // its reducer from these props once, so a base that arrives a render later
  // would leave the Changes view comparing the draft against nothing.
  const awaitingParent =
    version?.created_from_version_id !== null && version !== null && parentQuery.isPending;
  if (versionQuery.isLoading || gridsQuery.isLoading || !version || awaitingParent) {
    return <Skeleton className="h-[32rem] w-full rounded-xl" />;
  }

  // Editing needs the grid's discipline and its native-ladder declaration: without them a save would
  // rewrite stored native links as unlinked, so the editor stays closed instead of guessing.
  if (discipline === null || metadataQuery.isError || metadataInvalid) {
    return (
      <PageStateCard
        state="error"
        headingLevel={1}
        title={t("versionLoadError.title")}
        description={t("versionLoadError.description")}
        actionLabel={t("retry")}
        onAction={() => void metadataQuery.refetch()}
      />
    );
  }
  if (metadata === undefined) {
    return <Skeleton className="h-[32rem] w-full rounded-xl" />;
  }

  return (
    <DraftEditor
      key={`${version.id}:${epoch}`}
      workspaceId={workspaceId}
      discipline={discipline}
      capabilities={metadata.discipline.capabilities}
      ladder={ladder}
      version={version}
      base={parentQuery.data ? bandsFromTiers(ladder, parentQuery.data.tiers) : []}
      baseLabel={parentQuery.data ? `v${parentQuery.data.version}` : ""}
      readiness={readinessQuery.data ?? null}
      activeVersionId={activeVersionId}
      editable={version.status === "draft" && canUpdate}
      canPublish={canUpdate}
      canDelete={canDelete}
      initialChoices={carriedChoices}
      onReload={(carry) => {
        setCarriedChoices(carry ?? {});
        setEpoch((current) => current + 1);
      }}
    />
  );
}
