"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { ArrowRight, Download, Star, Upload, Wand2 } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useFormatter } from "next-intl";

import { AdminDataTable } from "@/components/data-table";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { StatusPill } from "@/components/kit/StatusPill";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useQueryParams } from "@/hooks/useQueryParams";
import { usePermissions, type AppPermission } from "@/hooks/usePermissions";
import { OW_REFERENCE_GRID } from "@/lib/division-grid";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import workspaceService from "@/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type {
  DivisionGridPortableDocument,
  DivisionGridReadinessSource,
  DivisionGridVersion
} from "@/types/workspace.types";

import {
  bandIconUrl,
  bandRangeLabel,
  bandSize,
  bandsFromTiers,
  RANK_COUNT,
  tiersFromBands,
  type Band
} from "./editor/draftReducer";
import { LadderBar } from "./LadderBar";
import { VersionHistory } from "./VersionHistory";

const SOURCE_STATUS_TONE = {
  ok: "success",
  incomplete: "warning",
  missing: "danger"
} as const;

const SOURCE_STATUS_LABEL = {
  ok: "mapping complete",
  incomplete: "mapping incomplete",
  missing: "no mapping"
} as const;

const MONO_CAPTION = "font-mono text-label uppercase tracking-wider text-muted-foreground";

/**
 * The whole OW ladder as a saveable version — what "Load standard OW ladder"
 * writes.
 *
 * Derived by the same band conversion the editor uses, so the standard ladder
 * and a hand-edited draft cannot disagree about `rank_min` / `ow_rank_*`. No
 * tier carries an `id`, which is what makes the save a new version rather than
 * a rewrite of an existing one.
 */
const STANDARD_OW_TIERS = tiersFromBands(bandsFromTiers(OW_REFERENCE_GRID.tiers));

/** The built-in ladder as bands: 45 one-rank divisions, what an unactivated workspace resolves through. */
const BUILT_IN_BANDS = bandsFromTiers(OW_REFERENCE_GRID.tiers);

/**
 * Settings › Divisions (T5 section, F11): what grid is in force, the version
 * history behind it, and the one thing worth doing next.
 *
 * The section renders bare — the settings layout owns the page header, the rail
 * and the `<main>`. The editor is a full-screen route of its own and the
 * importer is a wizard, because a version is either immutable or a draft and
 * only one of those is worth 1000 lines of editor.
 *
 * The active version is read from the workspace, not from the grid list: a
 * workspace may point at a version of a shared grid it does not own, and that
 * version is still the one every rank resolves through.
 */
export default function DivisionsSettingsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const format = useFormatter();
  const { searchParams, setParams } = useQueryParams();
  const { isSuperuser, canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const getCurrentWorkspace = useWorkspaceStore((state) => state.getCurrentWorkspace);
  const fetchWorkspaces = useWorkspaceStore((state) => state.fetchWorkspaces);
  const workspace = getCurrentWorkspace();
  const activeVersionId = workspace?.default_division_grid_version_id ?? null;
  const portableInputRef = useRef<HTMLInputElement>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [activating, setActivating] = useState<DivisionGridVersion | null>(null);

  const permitted = (permission: AppPermission) =>
    workspaceId !== null && (isSuperuser || canAccessPermission(permission, workspaceId));
  const canRead = permitted("division_grid.read");
  const canCreate = permitted("division_grid.create");
  const canActivate = permitted("division_grid.update");

  const gridsQuery = useQuery({
    queryKey: ["division-grids", workspaceId],
    queryFn: () => workspaceService.getDivisionGrids(workspaceId!),
    enabled: canRead
  });
  const grids = useMemo(() => gridsQuery.data ?? [], [gridsQuery.data]);

  const gridParam = Number(searchParams?.get("grid"));
  const selectedGrid =
    grids.find((grid) => grid.id === gridParam) ??
    grids.find((grid) => grid.versions.some((version) => version.id === activeVersionId)) ??
    grids.find((grid) => grid.archived_at === null) ??
    grids[0] ??
    null;

  const versionsQuery = useQuery({
    queryKey: ["division-grid-versions", workspaceId, selectedGrid?.id ?? null],
    queryFn: () => workspaceService.getDivisionGridVersions(workspaceId!, selectedGrid!.id),
    enabled: canRead && selectedGrid !== null
  });
  const versions = versionsQuery.data ?? selectedGrid?.versions ?? [];
  const latestVersion =
    [...versions].sort((left, right) => right.version - left.version)[0] ?? null;
  const draft =
    [...versions]
      .filter((version) => version.status === "draft")
      .sort((left, right) => right.version - left.version)[0] ?? null;
  const activeVersion =
    versions.find((version) => version.id === activeVersionId) ??
    workspace?.default_division_grid_version ??
    null;
  const activeIsShared =
    activeVersion !== null && !grids.some((grid) => grid.id === activeVersion.grid_id);

  const readinessQuery = useQuery({
    queryKey: ["division-grid-readiness", workspaceId, activeVersionId],
    queryFn: () => workspaceService.getDivisionGridVersionReadiness(workspaceId!, activeVersionId!),
    enabled: canRead && activeVersionId !== null
  });
  const sources = readinessQuery.data?.sources ?? [];
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
      canActivate
        ? versions
            .filter((version) => version.status === "published" && version.id !== activeVersionId)
            .sort((left, right) => right.version - left.version)
        : [],
    [activeVersionId, canActivate, versions]
  );
  const candidateReadiness = useQueries({
    queries: candidates.map((version) => ({
      queryKey: ["division-grid-readiness", workspaceId, version.id],
      queryFn: () => workspaceService.getDivisionGridVersionReadiness(workspaceId!, version.id),
      enabled: canRead
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
    () => (activeVersion ? bandsFromTiers(activeVersion.tiers) : []),
    [activeVersion]
  );

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["division-grids", workspaceId] }),
      queryClient.invalidateQueries({ queryKey: ["division-grid-versions", workspaceId] }),
      queryClient.invalidateQueries({ queryKey: ["division-grid-readiness", workspaceId] }),
      fetchWorkspaces()
    ]);
  };

  const editorHref = (versionId: number) => `/admin/settings/divisions/v/${versionId}`;

  const cloneMutation = useMutation({
    mutationFn: () => workspaceService.cloneDivisionGridVersion(latestVersion!.id),
    onSuccess: async (version) => {
      await refresh();
      notify.success(`Draft v${version.version} created`);
      router.push(editorHref(version.id));
    },
    onError: reportFailure("Draft could not be created")
  });

  const standardMutation = useMutation({
    mutationFn: () =>
      workspaceService.createDivisionGridVersion(workspaceId!, selectedGrid!.id, {
        label: "Standard OW ladder",
        tiers: STANDARD_OW_TIERS
      }),
    onSuccess: async (version) => {
      await refresh();
      notify.success(`Draft v${version.version} loaded with the standard ladder`);
      router.push(editorHref(version.id));
    },
    onError: reportFailure("Standard ladder could not be loaded")
  });

  const activateMutation = useMutation({
    mutationFn: (version: DivisionGridVersion) =>
      workspaceService.activateDivisionGridVersion(workspaceId!, version.id),
    onSuccess: async (version) => {
      setActivating(null);
      await refresh();
      notify.success(`v${version.version} is now the workspace grid`);
    },
    onError: reportFailure("Version could not be activated")
  });

  const portableImportMutation = useMutation({
    mutationFn: (document: DivisionGridPortableDocument) =>
      workspaceService.importDivisionGridPortable(workspaceId!, document),
    onSuccess: async (grid) => {
      await refresh();
      setParams({ grid: String(grid.id) });
      notify.success("Division grid imported from JSON");
    },
    onError: reportFailure("JSON import failed")
  });

  const exportPortable = async () => {
    if (!selectedGrid) return;
    setPendingAction("export");
    try {
      const document = await workspaceService.exportDivisionGridPortable(selectedGrid.id);
      const blob = new Blob([JSON.stringify(document, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = `${selectedGrid.slug}.division-grid.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      reportFailure("JSON export failed")(error);
    } finally {
      setPendingAction(null);
    }
  };

  const importPortable = async (file: File) => {
    try {
      portableImportMutation.mutate(JSON.parse(await file.text()) as DivisionGridPortableDocument);
    } catch (error) {
      notify.error("Invalid division grid JSON", {
        description: `Nothing was imported. ${
          error instanceof Error ? error.message : "The file is not valid JSON."
        } Export a grid from another workspace and import that file unchanged.`
      });
    } finally {
      if (portableInputRef.current) portableInputRef.current.value = "";
    }
  };

  const columns = useMemo<ColumnDef<Band>[]>(
    () => [
      {
        id: "number",
        header: "#",
        size: 52,
        cell: ({ row }) => <span className="font-mono tabular-nums">{row.original.number}</span>
      },
      {
        id: "name",
        header: "Division",
        cell: ({ row }) => (
          <span className="flex min-w-0 items-center gap-2">
            <Image
              src={bandIconUrl(row.original)}
              alt=""
              width={20}
              height={20}
              unoptimized
              className="size-5 shrink-0"
            />
            <span className="truncate font-medium">{row.original.name}</span>
          </span>
        )
      },
      {
        id: "band",
        header: "OW band",
        cell: ({ row }) => <span className="font-mono text-sm">{bandRangeLabel(row.original)}</span>
      },
      {
        id: "ranks",
        header: "Ranks",
        size: 76,
        cell: ({ row }) => <span className="font-mono tabular-nums">{bandSize(row.original)}</span>
      }
    ],
    []
  );

  if (workspaceId === null) {
    return (
      <PageStateCard
        state="empty"
        title="No workspace selected"
        description="Pick a workspace to manage its division grid."
      />
    );
  }

  if (!canRead) {
    return (
      <PageStateCard
        state="not-found"
        title="Divisions are not available to you"
        description="Reading the division grid needs the division_grid.read permission in this workspace."
      />
    );
  }

  if (gridsQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title="Division grids could not be loaded"
        description="The list of grids failed to load, so nothing below is trustworthy."
        actionLabel="Retry"
        onAction={() => void gridsQuery.refetch()}
      />
    );
  }

  if (gridsQuery.isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-40 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  // The one thing worth doing next, ranked: finish the draft, put a finished
  // version in force, start a draft, start from the standard ladder.
  const nextAction = draft ? (
    <Button size="sm" asChild>
      <Link href={editorHref(draft.id)}>
        Open draft v{draft.version}
        <ArrowRight aria-hidden className="size-3.5" />
      </Link>
    </Button>
  ) : readyCandidate ? (
    <Button size="sm" onClick={() => setActivating(readyCandidate)}>
      <Star aria-hidden className="size-3.5" />
      Activate v{readyCandidate.version}
    </Button>
  ) : canCreate && latestVersion ? (
    <Button size="sm" onClick={() => cloneMutation.mutate()} disabled={cloneMutation.isPending}>
      New draft from v{latestVersion.version}
    </Button>
  ) : canCreate && selectedGrid ? (
    <Button
      size="sm"
      onClick={() => standardMutation.mutate()}
      disabled={standardMutation.isPending}
    >
      <Wand2 aria-hidden className="size-3.5" />
      Load standard OW ladder
    </Button>
  ) : null;

  return (
    <div className="flex flex-col gap-6">
      <section
        aria-labelledby="divisions-in-force"
        className={cn(
          "rounded-xl p-4 sm:p-5",
          activeVersion
            ? "border border-primary/30 bg-primary/5"
            : "border border-dashed border-border"
        )}
      >
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <p className={cn(EYEBROW_CLASS, activeVersion && "text-primary/80")}>
              In force{activeVersion ? ` · v${activeVersion.version}` : ""}
            </p>
            <h2
              id="divisions-in-force"
              className="mt-1 font-display text-2xl font-semibold leading-tight tracking-tight"
            >
              {activeVersion ? activeVersion.label : "Built-in Overwatch ladder"}
            </h2>
            <p className={cn(MONO_CAPTION, "mt-1.5")}>
              {activeVersion
                ? [
                    `${activeBands.length} divisions`,
                    `${RANK_COUNT} ranks`,
                    activeVersion.published_at
                      ? `published ${format.dateTime(new Date(activeVersion.published_at), {
                          dateStyle: "medium"
                        })}`
                      : null,
                    activeIsShared ? "shared grid" : null
                  ]
                    .filter(Boolean)
                    .join(" · ")
                : `${RANK_COUNT} ranks · nothing activated`}
            </p>
          </div>
          {nextAction ? (
            <div className="flex shrink-0 flex-col items-start gap-1.5 lg:items-end">
              <span className={EYEBROW_CLASS}>Next step</span>
              {nextAction}
            </div>
          ) : null}
        </div>

        <LadderBar
          bands={activeVersion ? activeBands : BUILT_IN_BANDS}
          size="lg"
          tone={activeVersion ? "accent" : "neutral"}
          className="mt-4"
        />

        <p className="mt-3 max-w-prose text-xs text-muted-foreground">
          {activeVersion
            ? activeIsShared
              ? "This version belongs to a grid shared with other workspaces, so it cannot be edited here. Load a ladder or create a draft in this workspace's own grid, then activate it to take over."
              : `Every rank in this workspace resolves through v${activeVersion.version} until another version is published and activated.`
            : "No version is active, so ranks resolve one-to-one through the standard ladder. Publish and activate a version to sort players into your own divisions."}
        </p>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(18rem,22rem)]">
        <section className="flex min-w-0 flex-col gap-3" aria-labelledby="divisions-history">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <h2 id="divisions-history" className="font-display text-base font-semibold">
                Version history
              </h2>
              <p className="mt-0.5 max-w-prose text-xs text-muted-foreground">
                A division is a band of the Overwatch ladder. Published versions are immutable —
                every tournament keeps the version it was played on, and a mapping translates its
                divisions into the version in force.
              </p>
            </div>
            {canCreate ? (
              <div className="flex flex-wrap gap-2">
                {latestVersion ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => cloneMutation.mutate()}
                    disabled={cloneMutation.isPending}
                  >
                    + New draft from v{latestVersion.version}
                  </Button>
                ) : null}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => standardMutation.mutate()}
                  disabled={standardMutation.isPending || selectedGrid === null}
                >
                  <Wand2 aria-hidden className="size-3.5" />
                  Load standard OW ladder
                </Button>
              </div>
            ) : null}
          </div>

          {grids.length > 1 ? (
            <div className="flex items-center gap-2">
              <label className={EYEBROW_CLASS} htmlFor="division-grid-select">
                Grid
              </label>
              <Select
                value={selectedGrid ? String(selectedGrid.id) : undefined}
                onValueChange={(value) => setParams({ grid: value })}
              >
                <SelectTrigger id="division-grid-select" className="h-9 w-72">
                  <SelectValue placeholder="Choose a grid" />
                </SelectTrigger>
                <SelectContent>
                  {grids.map((grid) => (
                    <SelectItem key={grid.id} value={String(grid.id)}>
                      {grid.name}
                      {grid.archived_at ? " (archived)" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}

          {versions.length === 0 ? (
            <EmptyNote title="No versions yet">
              Load the standard Overwatch ladder to start, or import a grid from another workspace.
            </EmptyNote>
          ) : (
            <VersionHistory
              versions={versions}
              activeVersionId={activeVersionId}
              tournamentCounts={tournamentCounts}
              activatable={activatable}
              onActivate={setActivating}
              editorHref={editorHref}
            />
          )}

          <div className="flex flex-wrap items-center gap-x-1 gap-y-1">
            <span className={cn(EYEBROW_CLASS, "mr-2")}>Transfer</span>
            {canCreate ? (
              <>
                <input
                  ref={portableInputRef}
                  type="file"
                  accept="application/json,.json"
                  className="hidden"
                  aria-hidden
                  tabIndex={-1}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) void importPortable(file);
                  }}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => portableInputRef.current?.click()}
                  disabled={portableImportMutation.isPending}
                >
                  <Upload aria-hidden className="size-3.5" />
                  Import JSON
                </Button>
              </>
            ) : null}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void exportPortable()}
              disabled={selectedGrid === null || pendingAction === "export"}
            >
              <Download aria-hidden className="size-3.5" />
              Export JSON
            </Button>
            {canCreate ? (
              <Button variant="ghost" size="sm" asChild>
                <Link href="/admin/settings/divisions/import">Import from workspace…</Link>
              </Button>
            ) : null}
          </div>
        </section>

        <section className="flex min-w-0 flex-col gap-3" aria-labelledby="divisions-readers">
          <h2 id="divisions-readers" className="font-display text-base font-semibold">
            Who reads which version
          </h2>
          {!activeVersion ? (
            <p className="text-xs text-muted-foreground">
              Once a version is in force, this lists the older versions tournaments still read and
              whether their divisions map onto it.
            </p>
          ) : readinessQuery.isLoading ? (
            <Skeleton className="h-32 w-full rounded-xl" />
          ) : sources.length === 0 ? (
            <EmptyNote size="sm">
              Every tournament in this workspace reads v{activeVersion.version}. Nothing to map.
            </EmptyNote>
          ) : (
            <ul className="flex flex-col gap-3">
              {sources.map((source) => (
                <SourceCard key={source.version_id} source={source} target={activeVersion} />
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="flex min-w-0 flex-col gap-3" aria-labelledby="divisions-table">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="divisions-table" className="font-display text-base font-semibold">
            Divisions in force
          </h2>
          {activeVersion ? (
            <span className={MONO_CAPTION}>
              v{activeVersion.version} · {activeVersion.label}
            </span>
          ) : null}
        </div>
        {activeVersion ? (
          <AdminDataTable<Band>
            rows={activeBands}
            columns={columns}
            getRowId={(row) => row.slug}
            initialPageSize={50}
            emptyMessage="This version has no divisions."
          />
        ) : (
          <EmptyNote size="sm">
            Players are sorted by their Overwatch rank directly until a version is activated.
          </EmptyNote>
        )}
      </section>

      <ConfirmDialog
        open={activating !== null}
        onOpenChange={(open) => {
          if (!open) setActivating(null);
        }}
        intent={{
          title: `Activate v${activating?.version ?? ""}?`,
          description: `Every rank in this workspace will resolve through v${
            activating?.version ?? ""
          } from now on. Tournaments keep the version they were played on${
            activeVersion ? `, and v${activeVersion.version} stays in the history` : ""
          }.`,
          confirmLabel: `Activate v${activating?.version ?? ""}`,
          tone: "neutral"
        }}
        pending={activateMutation.isPending}
        onConfirm={() => {
          if (activating) activateMutation.mutate(activating);
        }}
      />
    </div>
  );
}

/**
 * One older version tournaments still read, and whether its divisions have a
 * way into the version in force. The readiness payload names the five newest
 * tournaments and counts all of them, so the list is shown as a sample, never
 * as the whole.
 */
function SourceCard({
  source,
  target
}: Readonly<{ source: DivisionGridReadinessSource; target: DivisionGridVersion }>) {
  const hidden = source.tournament_count - source.tournament_names.length;
  return (
    <li className="flex flex-col gap-2 rounded-xl border border-border bg-card p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium" title={source.version_label}>
            {source.version_label}
          </p>
          <p className="truncate text-xs text-muted-foreground" title={source.grid_name}>
            {source.grid_name}
          </p>
        </div>
        <StatusPill tone={SOURCE_STATUS_TONE[source.status]}>
          {SOURCE_STATUS_LABEL[source.status]}
        </StatusPill>
      </div>

      <p className={MONO_CAPTION}>
        {source.tournament_count} {source.tournament_count === 1 ? "tournament" : "tournaments"}
      </p>
      {source.tournament_names.length > 0 ? (
        <ul className="flex flex-col gap-0.5 text-xs">
          {source.tournament_names.map((name) => (
            <li key={name} className="truncate" title={name}>
              {name}
            </li>
          ))}
          {hidden > 0 ? <li className="text-muted-foreground">+{hidden} more</li> : null}
        </ul>
      ) : null}

      {source.status === "ok" ? null : (
        <p className="text-xs text-muted-foreground">
          {source.status === "missing"
            ? `No mapping into v${target.version} yet, so players from these tournaments cannot be translated into the current divisions.`
            : `${source.conflict_tiers.length} of its divisions have no target in v${target.version} yet.`}{" "}
          Create a draft, resolve its Mappings view, then publish and activate it.
        </p>
      )}
    </li>
  );
}

function reportFailure(title: string) {
  return (error: unknown) =>
    notify.error(title, {
      description: `Nothing changed. ${
        error instanceof Error ? error.message : "The division grid operation failed."
      } Retry, or reload the page if it keeps failing.`
    });
}
