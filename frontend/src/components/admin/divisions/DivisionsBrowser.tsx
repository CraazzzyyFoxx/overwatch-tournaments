"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";

import {
  bandsFromTiers,
  createLadder,
  standardTiers,
  type Band
} from "@/app/admin/settings/divisions/editor/draftReducer";
import { gameFilterDefs } from "@/components/admin/game-filter";
import { DataTable } from "@craazzzyyfoxx/admin-kit/data-table";
import { ConfirmDialog, type ConfirmIntent } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { FilterBar } from "@craazzzyyfoxx/admin-kit/kit/FilterBar";
import { useFilters } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { useFilePicker } from "@/components/ui/file-button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { GameScopeControl } from "@/components/workspace/GameScopeControl";
import { useGameScope } from "@/hooks/useGameScope";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useQueryParams } from "@/hooks/useQueryParams";
import { useWorkspaceRead } from "@/hooks/useCurrentWorkspace";
import { usePermissions } from "@/hooks/usePermissions";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { activeGridVersionId, resolveOwnerGrid } from "@/lib/divisions/grid";
import { divisionGridQueryKeys } from "@/lib/divisions/query-keys";
import { getApiErrorMessage } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import workspaceService from "@/services/workspace.service";
import type { DivisionGridEntity, DivisionGridVersion } from "@/types/workspace.types";

import { DivisionsHeaderActions } from "./DivisionsHeaderActions";
import { GamesSummary, GamesSummarySkeleton } from "./GamesSummary";
import { GridFormDialog, type GridForm } from "./GridFormDialog";
import { GridInForceSection } from "./GridInForceSection";
import { GridMenu } from "./GridMenu";
import { GridSection } from "./GridSection";
import { editorHref } from "./model";
import { ReadersSection } from "./ReadersSection";
import { reportFailure, useGridActions, type SubmitScope } from "./useGridActions";
import { useDivisionColumns } from "./useDivisionColumns";

/** The one confirmation surface of the page, with a swapped intent (DESIGN §14). */
type Confirming =
  | { kind: "activate"; version: DivisionGridVersion }
  | { kind: "delete"; grid: DivisionGridEntity };

/** What the in-force card offers next, ranked; the grid menu leaves out whichever it is. */
type NextStep = "openDraft" | "activate" | "newDraft" | "ladderDraft" | "createGrid";

/**
 * Settings › Divisions. Under "all games" a summary row per game; for one game, the grid in force, the open grid with
 * its version history and menu, and the divisions in force.
 *
 * The editor is a full-screen route of its own and the importer is a wizard, because a version is either immutable or
 * a draft and only one of those is worth 1000 lines of editor.
 *
 * The active version is read from the workspace, not from the grid list: a workspace may point at a version of a
 * shared grid it does not own, and that version is still the one every rank resolves through.
 */
export function DivisionsBrowser({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const t = useTranslations("adminSettings.divisions");
  const gameT = useTranslations("common.discipline");
  const router = useRouter();
  const queryClient = useQueryClient();
  const { searchParams, setParams } = useQueryParams();
  const { isSuperuser, canAccessPermission } = usePermissions();
  const workspace = useWorkspaceRead(workspaceId);
  const [confirming, setConfirming] = useState<Confirming | null>(null);
  const [gridForm, setGridForm] = useState<GridForm | null>(null);

  const can = (action: "create" | "update" | "delete") =>
    isSuperuser || canAccessPermission(`division_grid.${action}`, workspaceId);
  const canCreate = can("create");
  const canUpdate = can("update");
  const canDelete = can("delete");

  const gridsQuery = useQuery({
    queryKey: divisionGridQueryKeys.grids(workspaceId),
    queryFn: () => workspaceService.getDivisionGrids(workspaceId)
  });
  const grids = useMemo(() => gridsQuery.data ?? [], [gridsQuery.data]);

  // An explicitly opened `?grid=` is an OWNER (spec §5, §6.12): its own game is the page's, whatever `?discipline=`
  // says. Without a pin the index is a multi page: a summary of every game, or one game under the game filter.
  const gridParam = Number(searchParams?.get("grid"));
  const hasGridPin = searchParams?.has("grid") === true;
  const ownerGrid = hasGridPin ? (grids.find((grid) => grid.id === gridParam) ?? null) : null;
  const gameScope = useGameScope({
    pageClass: ownerGrid ? "owner" : "multi",
    axis: workspaceId,
    ownerGame: ownerGrid?.discipline ?? null
  });
  // Picking another game than the pinned grid's unpins it, or the pick would show nothing; clearing the filter keeps it.
  const gameDefs = gameFilterDefs(
    gameScope.games,
    gameT("column"),
    (next) => (ownerGrid !== null && next !== null && next !== ownerGrid.discipline ? ["grid"] : []),
    gameT("all")
  );
  const filters = useFilters(gameDefs);
  const enabledGames = useMemo(() => (gameScope.games ?? []).filter((game) => game.enabled), [gameScope.games]);
  const discipline = gameScope.game;
  const descriptor = gameScope.games?.find((game) => game.code === discipline);
  const game = descriptor?.short_name || discipline || "";

  const gameGrids = useMemo(
    () => (discipline === null ? [] : grids.filter((grid) => grid.discipline === discipline)),
    [discipline, grids]
  );
  const activeVersionId = activeGridVersionId(workspace, discipline);
  const selectedGrid =
    gameGrids.find((grid) => grid.id === gridParam) ??
    gameGrids.find((grid) => grid.versions.some((version) => version.id === activeVersionId)) ??
    gameGrids.find((grid) => grid.archived_at === null) ??
    gameGrids[0] ??
    null;

  const metadataQuery = useDisciplineMetadata(workspaceId, discipline);
  const metadata = metadataQuery.data;
  const ladder = useMemo(
    () => (metadata?.discipline.capabilities.native_ladder ? createLadder(metadata.native_ladder) : null),
    [metadata]
  );
  // A declared native ladder with no ranks is invalid metadata, never "no ladder".
  const metadataInvalid =
    metadata !== undefined && metadata.discipline.capabilities.native_ladder && ladder === null;
  // The game's own ladder as saveable tiers, and what resolves while nothing is in force.
  const ladderTiers = useMemo(() => (ladder ? standardTiers(ladder) : null), [ladder]);
  const builtInBands = useMemo(
    () => (ladder && ladderTiers ? bandsFromTiers(ladder, ladderTiers) : []),
    [ladder, ladderTiers]
  );

  const versionsQuery = useQuery({
    queryKey: divisionGridQueryKeys.versions(workspaceId, discipline, selectedGrid?.id ?? null),
    queryFn: () => workspaceService.getDivisionGridVersions(workspaceId, selectedGrid!.id),
    enabled: selectedGrid !== null
  });
  const versions = useMemo(
    () => versionsQuery.data ?? selectedGrid?.versions ?? [],
    [selectedGrid, versionsQuery.data]
  );
  const latestVersion = [...versions].sort((left, right) => right.version - left.version)[0] ?? null;
  const draft =
    [...versions]
      .filter((version) => version.status === "draft")
      .sort((left, right) => right.version - left.version)[0] ?? null;
  const activeVersion = useMemo(
    () =>
      versions.find((version) => version.id === activeVersionId) ?? resolveOwnerGrid(workspace, discipline) ?? null,
    [activeVersionId, discipline, versions, workspace]
  );
  const activeGrid = activeVersion ? (grids.find((grid) => grid.id === activeVersion.grid_id) ?? null) : null;
  const selectedInForce = versions.some((version) => version.id === activeVersionId);

  const readinessQuery = useQuery({
    queryKey: divisionGridQueryKeys.readiness(workspaceId, discipline, activeVersionId),
    queryFn: () => workspaceService.getDivisionGridVersionReadiness(workspaceId, activeVersionId!),
    enabled: activeVersionId !== null
  });
  const sources = useMemo(() => readinessQuery.data?.sources ?? [], [readinessQuery.data]);
  const tournamentCounts = useMemo(
    () =>
      readinessQuery.data
        ? Object.fromEntries(sources.map((source) => [source.version_id, source.tournament_count]))
        : null,
    [readinessQuery.data, sources]
  );

  // Published versions the workspace is not on yet: each needs its own
  // readiness to know whether "Activate" is honest right now.
  const candidates = useMemo(
    () =>
      canUpdate
        ? versions
            .filter((version) => version.status === "published" && version.id !== activeVersionId)
            .sort((left, right) => right.version - left.version)
        : [],
    [activeVersionId, canUpdate, versions]
  );
  const candidateReadiness = useQueries({
    queries: candidates.map((version) => ({
      queryKey: divisionGridQueryKeys.readiness(workspaceId, discipline, version.id),
      queryFn: () => workspaceService.getDivisionGridVersionReadiness(workspaceId, version.id)
    }))
  });
  const activatable = useMemo(
    () =>
      Object.fromEntries(
        candidates.map((version, index) => [version.id, candidateReadiness[index]?.data?.is_ready])
      ) as Record<number, boolean | undefined>,
    [candidates, candidateReadiness]
  );
  const readyCandidate = candidates.find((version) => activatable[version.id] === true) ?? null;

  const activeBands = useMemo(
    () => (activeVersion ? bandsFromTiers(ladder, activeVersion.tiers) : builtInBands),
    [activeVersion, builtInBands, ladder]
  );

  const submitScope: SubmitScope = { workspaceId, discipline: discipline ?? "" };
  const refresh = async (scope: SubmitScope) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: divisionGridQueryKeys.grids(scope.workspaceId) }),
      queryClient.invalidateQueries({
        queryKey: divisionGridQueryKeys.versionsByDiscipline(scope.workspaceId, scope.discipline)
      }),
      queryClient.invalidateQueries({
        queryKey: divisionGridQueryKeys.readinessByDiscipline(scope.workspaceId, scope.discipline)
      }),
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.workspace(scope.workspaceId) })
    ]);
  };

  const actions = useGridActions({
    workspaceId,
    refresh,
    onOpen: (grid) => setParams({ grid: String(grid.id), discipline: grid.discipline }),
    onDeleted: (grid) => {
      if (gridParam === grid.id) setParams({ grid: null });
    }
  });
  const portablePicker = useFilePicker({
    accept: "application/json,.json",
    onFiles: ([file]) => void actions.importFile(file)
  });

  const cloneMutation = useMutation({
    mutationFn: (input: { scope: SubmitScope; versionId: number }) =>
      workspaceService.cloneDivisionGridVersion(input.versionId),
    onSuccess: async (version, input) => {
      await refresh(input.scope);
      notify.success(t("toast.draftCreated", { version: version.version }));
      router.push(editorHref(version.id));
    },
    onError: reportFailure(t("errors.draftCreate"), t)
  });

  const ladderDraftMutation = useMutation({
    mutationFn: (input: { scope: SubmitScope; gridId: number; tiers: typeof ladderTiers }) => {
      if (!input.tiers) throw new Error(t("errors.noStandardLadder"));
      return workspaceService.createDivisionGridVersion(input.scope.workspaceId, input.gridId, {
        label: t("standardLadder", { game }),
        tiers: input.tiers
      });
    },
    onSuccess: async (version, input) => {
      await refresh(input.scope);
      notify.success(t("toast.standardLoaded", { version: version.version, game }));
      router.push(editorHref(version.id));
    },
    onError: reportFailure(t("errors.standardLoad"), t)
  });

  const activateMutation = useMutation({
    mutationFn: async (input: { scope: SubmitScope; version: DivisionGridVersion; ownVersionIds: number[] }) => {
      // Defaults are per game: a version that is not one of the open grid's own is never activated here.
      if (!input.ownVersionIds.includes(input.version.id)) {
        throw new Error(t("errors.activateWrongGame"));
      }
      return workspaceService.activateDivisionGridVersion(input.scope.workspaceId, input.version.id);
    },
    onSuccess: async (version, input) => {
      setConfirming(null);
      await refresh(input.scope);
      notify.success(t("toast.activated", { version: version.version }));
    },
    onError: reportFailure(t("errors.activate"), t)
  });

  const columns = useDivisionColumns(ladder, game);

  const newDraft = () => {
    if (latestVersion) cloneMutation.mutate({ scope: submitScope, versionId: latestVersion.id });
  };
  const ladderDraft = () => {
    if (selectedGrid) ladderDraftMutation.mutate({ scope: submitScope, gridId: selectedGrid.id, tiers: ladderTiers });
  };
  const formError = (error: Error | null) => (error ? getApiErrorMessage(error, t("operationFailed")) : undefined);

  const resolution = gameScope.resolution;
  const summary = resolution?.game.kind === "all";

  if (gridsQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title={t("loadError.title")}
        description={t("loadError.description")}
        actionLabel={t("retry")}
        onAction={() => void gridsQuery.refetch()}
      />
    );
  }

  // Nothing game-shaped is read or drawn until the games are known: an explicit invalid `?discipline=` is named,
  // never corrected.
  if (resolution === null && gameScope.isError) {
    return (
      <PageStateCard
        state="error"
        title={t("loadError.title")}
        description={t("loadError.description")}
        actionLabel={t("retry")}
        onAction={gameScope.refetch}
      />
    );
  }
  if (resolution !== null && (resolution.game.kind === "invalid" || resolution.game.kind === "empty")) {
    return <GameScopeControl scope={gameScope} variant="multi" />;
  }
  if (discipline !== null && (metadataQuery.isError || metadataInvalid)) {
    return (
      <PageStateCard
        state="error"
        title={t("loadError.title")}
        description={t("loadError.description")}
        actionLabel={t("retry")}
        onAction={() => void metadataQuery.refetch()}
      />
    );
  }
  if (gridsQuery.isLoading || resolution === null || (discipline !== null && metadata === undefined)) {
    return summary && !hasGridPin ? (
      <GamesSummarySkeleton rows={Math.max(enabledGames.length, 2)} />
    ) : (
      <GameSkeleton />
    );
  }

  // The one thing worth doing next, ranked: finish the draft, put a finished version in force, start a draft from
  // the newest version, start one from the ladder; a game with no grid of its own gets one.
  const nextStep: NextStep | null =
    selectedGrid === null
      ? canCreate && discipline !== null
        ? "createGrid"
        : null
      : draft
        ? "openDraft"
        : readyCandidate
          ? "activate"
          : canCreate && latestVersion
            ? "newDraft"
            : canCreate && ladder
              ? "ladderDraft"
              : null;
  const nextAction =
    nextStep === "openDraft" && draft ? (
      <Button size="sm" asChild>
        <Link href={editorHref(draft.id)}>{t("openDraft", { version: draft.version })}</Link>
      </Button>
    ) : nextStep === "activate" && readyCandidate ? (
      <Button size="sm" onClick={() => setConfirming({ kind: "activate", version: readyCandidate })}>
        {t("activateVersion", { version: readyCandidate.version })}
      </Button>
    ) : nextStep === "newDraft" && latestVersion ? (
      <Button size="sm" onClick={newDraft} disabled={cloneMutation.isPending}>
        {t("newDraft", { version: latestVersion.version })}
      </Button>
    ) : nextStep === "ladderDraft" ? (
      <Button size="sm" onClick={ladderDraft} disabled={ladderDraftMutation.isPending}>
        {t("gridMenu.draftFromLadder", { game })}
      </Button>
    ) : nextStep === "createGrid" ? (
      <Button size="sm" onClick={() => setGridForm({ mode: "create", game: discipline })}>
        {t("createGameGrid", { game })}
      </Button>
    ) : null;

  const menu = selectedGrid ? (
    <GridMenu
      grid={selectedGrid}
      inForce={selectedInForce}
      // A draft in hand is opened, not doubled.
      newDraft={
        canCreate && latestVersion && !draft && nextStep !== "newDraft"
          ? { label: t("newDraft", { version: latestVersion.version }), onSelect: newDraft }
          : null
      }
      ladderDraft={
        canCreate && ladder && nextStep !== "ladderDraft"
          ? { label: t("gridMenu.draftFromLadder", { game }), onSelect: ladderDraft }
          : null
      }
      onRename={canUpdate ? () => setGridForm({ mode: "rename", grid: selectedGrid }) : null}
      onExport={() => void actions.exportPortable(selectedGrid)}
      onArchive={canDelete ? () => actions.archive.mutate({ grid: selectedGrid, archived: true }) : null}
      onRestore={canUpdate ? () => actions.archive.mutate({ grid: selectedGrid, archived: false }) : null}
      onDelete={canDelete ? () => setConfirming({ kind: "delete", grid: selectedGrid }) : null}
      pending={actions.pending || cloneMutation.isPending || ladderDraftMutation.isPending}
    />
  ) : null;

  const confirmIntent = (): ConfirmIntent => {
    if (confirming?.kind === "delete") {
      const pinned = confirming.grid.tournament_count ?? 0;
      return pinned > 0
        ? {
            title: t("confirm.detachTitle", { name: confirming.grid.name }),
            description: t("confirm.detachDescription", { count: pinned, game }),
            confirmLabel: t("confirm.detachLabel"),
            tone: "danger",
            requireTyped: confirming.grid.name
          }
        : {
            title: t("confirm.deleteTitle", { name: confirming.grid.name }),
            description: t("confirm.deleteDescription", { count: confirming.grid.versions.length }),
            confirmLabel: t("confirm.deleteLabel"),
            tone: "danger"
          };
    }
    const version = confirming?.version.version ?? "";
    return {
      title: t("confirm.activateTitle", { version }),
      description: t("confirm.activateDescription", { version }),
      confirmLabel: t("activateVersion", { version }),
      tone: "neutral"
    };
  };

  return (
    <div className="flex flex-col gap-6">
      <DivisionsHeaderActions
        canCreate={canCreate}
        onNewGrid={() => setGridForm({ mode: "create", game: discipline })}
        onImportJson={portablePicker.open}
        importPending={actions.importPortable.isPending}
      />
      {gameDefs.length > 0 ? <FilterBar defs={gameDefs} filters={filters} /> : null}

      {summary ? (
        <GamesSummary workspaceId={workspaceId} games={enabledGames} workspace={workspace} grids={grids} />
      ) : (
        <>
          <GridInForceSection
            game={game}
            ladder={ladder}
            activeVersion={activeVersion}
            activeGrid={activeGrid}
            bands={activeBands}
            systemFallback={activeVersionId === null}
            nextAction={nextAction}
          />

          <div className="grid items-start gap-6 xl:grid-cols-2">
            <div className="flex min-w-0 flex-col gap-6">
              <GridSection
                game={game}
                grids={gameGrids}
                selectedGrid={selectedGrid}
                onSelectGrid={(value) => setParams({ grid: value })}
                menu={menu}
                versions={versions}
                ladder={ladder}
                activeVersionId={activeVersionId}
                tournamentCounts={tournamentCounts}
                activatable={activatable}
                onActivate={(version) => setConfirming({ kind: "activate", version })}
              />
              <ReadersSection activeVersion={activeVersion} loading={readinessQuery.isLoading} sources={sources} />
            </div>

            <section className="flex min-w-0 flex-col gap-3" aria-labelledby="divisions-table">
              <h2 id="divisions-table" className="text-ui font-semibold text-foreground">
                {t("divisionsInForce")}
              </h2>
              {activeBands.length > 0 ? (
                <DataTable<Band>
                  rows={activeBands}
                  columns={columns}
                  getRowId={(row) => row.slug}
                  initialPageSize={50}
                  emptyMessage={t("table.empty")}
                />
              ) : (
                <EmptyNote size="sm">{t("organizerGridRequired")}</EmptyNote>
              )}
            </section>
          </div>
        </>
      )}

      {canCreate ? portablePicker.input : null}

      {gridForm ? (
        <GridFormDialog
          key={gridForm.mode === "rename" ? `rename-${gridForm.grid.id}` : `create-${gridForm.game ?? "all"}`}
          form={gridForm}
          workspaceId={workspaceId}
          games={gameScope.games ?? []}
          workspace={workspace}
          grids={grids}
          pending={gridForm.mode === "create" ? actions.create.isPending : actions.rename.isPending}
          error={formError(gridForm.mode === "create" ? actions.create.error : actions.rename.error)}
          onClose={() => {
            actions.create.reset();
            actions.rename.reset();
            setGridForm(null);
          }}
          onSubmit={(values) => {
            const close = { onSuccess: () => setGridForm(null) };
            if (gridForm.mode === "create") actions.create.mutate({ workspaceId, values }, close);
            else actions.rename.mutate({ grid: gridForm.grid, name: values.name }, close);
          }}
        />
      ) : null}

      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(open) => {
          if (!open) setConfirming(null);
        }}
        intent={confirmIntent()}
        pending={activateMutation.isPending || actions.remove.isPending}
        onConfirm={() => {
          if (confirming?.kind === "activate") {
            activateMutation.mutate({
              scope: submitScope,
              version: confirming.version,
              ownVersionIds: versions.map((entry) => entry.id)
            });
          } else if (confirming?.kind === "delete") {
            actions.remove.mutate(
              { grid: confirming.grid, force: (confirming.grid.tournament_count ?? 0) > 0 },
              { onSuccess: () => setConfirming(null) }
            );
          }
        }}
      />
    </div>
  );
}

/** One game's skeleton: the in-force card, then the two columns, so nothing reflows when the data lands. */
function GameSkeleton() {
  return (
    <div aria-hidden className="flex flex-col gap-6">
      <Skeleton className="h-36 w-full rounded-xl" />
      <div className="grid gap-6 xl:grid-cols-2">
        <div className="flex flex-col gap-3">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-28 w-full rounded-xl" />
        </div>
        <div className="flex flex-col gap-3">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-64 w-full rounded-xl" />
        </div>
      </div>
    </div>
  );
}
