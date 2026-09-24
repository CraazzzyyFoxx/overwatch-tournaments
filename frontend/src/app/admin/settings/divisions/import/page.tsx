"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";

import { WizardShell, type WizardStep } from "@/components/kit/WizardShell";
import { StatusPill } from "@/components/kit/StatusPill";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useQueryParams } from "@/hooks/useQueryParams";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import workspaceService from "@/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { DivisionGridMarketplaceImportRequest } from "@/types/workspace.types";
import { Spinner } from "@/components/ui/spinner";

const STEPS = ["source", "version", "create"] as const;
type StepKey = (typeof STEPS)[number];

const STEP_LABELS: Record<StepKey, string> = {
  source: "Source",
  version: "Grid & version",
  create: "Create draft"
};

/**
 * Import a division grid from another workspace (T6, F12b).
 *
 * Three steps, because the fourth one the old `ImportWizard` had — resolving
 * conflicts — is not a step: mappings are a permanent view of the draft
 * editor, and this flow's only product is a draft. So it ends by opening that
 * draft with the Mappings tab in focus rather than by asking the user to
 * decide anything here.
 *
 * State lives in the query string (`step`, `source`, `grid`, `version`,
 * `job`), so a reload during a slow import resumes on the polling step instead
 * of starting over.
 */
export default function DivisionGridImportPage() {
  const router = useRouter();
  const { searchParams, setParams } = useQueryParams();
  const { isSuperuser, canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);

  const canImport =
    workspaceId !== null &&
    (isSuperuser || canAccessPermission("division_grid.create", workspaceId));

  const requestedStep = (searchParams?.get("step") ?? "source") as StepKey;
  const step: StepKey = STEPS.includes(requestedStep) ? requestedStep : "source";
  const sourceWorkspaceId = numberParam(searchParams, "source");
  const sourceGridId = numberParam(searchParams, "grid");
  const sourceVersionId = numberParam(searchParams, "version");
  const jobId = numberParam(searchParams, "job");
  const includeIcons = searchParams?.get("icons") !== "0";
  const includeOwRanks = searchParams?.get("ow") !== "0";

  const workspacesQuery = useQuery({
    queryKey: ["division-grid-import-workspaces", workspaceId],
    queryFn: () => workspaceService.getDivisionGridMarketplaceWorkspaces(workspaceId!),
    enabled: canImport
  });

  const gridsQuery = useQuery({
    queryKey: ["division-grid-import-grids", workspaceId, sourceWorkspaceId],
    queryFn: () => workspaceService.getDivisionGridMarketplace(workspaceId!, sourceWorkspaceId!),
    enabled: canImport && sourceWorkspaceId !== null
  });
  const grids = gridsQuery.data ?? [];
  const selectedGrid = grids.find((grid) => grid.id === sourceGridId) ?? null;

  const request = useMemo<DivisionGridMarketplaceImportRequest | null>(() => {
    if (sourceWorkspaceId === null || sourceGridId === null || sourceVersionId === null)
      return null;
    return {
      source_workspace_id: sourceWorkspaceId,
      source_grid_id: sourceGridId,
      source_version_id: sourceVersionId,
      include_icons: includeIcons,
      include_ow_rank_mappings: includeOwRanks
    };
  }, [includeIcons, includeOwRanks, sourceGridId, sourceVersionId, sourceWorkspaceId]);

  const preflightQuery = useQuery({
    queryKey: ["division-grid-import-preflight", workspaceId, request],
    queryFn: () => workspaceService.preflightDivisionGridMarketplace(workspaceId!, request!),
    enabled: canImport && request !== null
  });

  const jobQuery = useQuery({
    queryKey: ["division-grid-import-job", workspaceId, jobId],
    queryFn: () => workspaceService.getDivisionGridImportJob(workspaceId!, jobId!),
    enabled: canImport && jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 1000 : false;
    }
  });
  const job = jobQuery.data ?? null;

  const importedGridId = job?.result?.imported_grids[0]?.target_grid_id ?? null;
  const importedVersionsQuery = useQuery({
    queryKey: ["division-grid-versions", workspaceId, importedGridId],
    queryFn: () => workspaceService.getDivisionGridVersions(workspaceId!, importedGridId!),
    enabled: canImport && importedGridId !== null
  });

  const importMutation = useMutation({
    mutationFn: () => workspaceService.importDivisionGridMarketplace(workspaceId!, request!),
    onSuccess: (started) => setParams({ step: "create", job: String(started.id) }),
    onError: (error) =>
      notify.error("Import could not start", {
        description: `Nothing was copied into this workspace. ${
          error instanceof Error ? error.message : "The import request failed."
        } Re-check the workspace, grid and version, then try again.`
      })
  });

  /**
   * The draft the job produced.
   *
   * The job result names the target GRID, not the version, so the newest
   * version of that grid is the one just written — preferring a draft, since
   * that is the only kind this flow is allowed to produce.
   */
  const importedVersion = useMemo(() => {
    const versions = [...(importedVersionsQuery.data ?? [])].sort(
      (left, right) => right.version - left.version
    );
    return versions.find((version) => version.status === "draft") ?? versions[0] ?? null;
  }, [importedVersionsQuery.data]);

  if (workspaceId === null) {
    return (
      <PageStateCard
        state="empty"
        title="No workspace selected"
        description="Pick a workspace to import a division grid into."
      />
    );
  }

  if (!canImport) {
    return (
      <PageStateCard
        state="not-found"
        title="Importing is not available to you"
        description="Creating a division grid version needs the division_grid.create permission in this workspace."
      />
    );
  }

  const stepIndex = STEPS.indexOf(step);
  const steps: WizardStep[] = STEPS.map((key, index) => ({
    key,
    label: STEP_LABELS[key],
    state: index === stepIndex ? "current" : index < stepIndex ? "done" : "todo"
  }));

  const next =
    step === "source"
      ? {
          label: "Continue",
          disabled: sourceWorkspaceId === null,
          onClick: () => setParams({ step: "version" })
        }
      : step === "version"
        ? {
            label: "Create draft",
            disabled: request === null || importMutation.isPending,
            onClick: () => importMutation.mutate()
          }
        : {
            label: "Open the draft",
            disabled: importedVersion === null,
            onClick: () =>
              router.push(`/admin/settings/divisions/v/${importedVersion!.id}?tab=mappings`)
          };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="font-display text-lg font-semibold">Import from workspace</h2>
        <p className="text-sm text-muted-foreground">
          Copies a grid version in as a new draft. Nothing in this workspace changes until you
          publish and activate it.
        </p>
      </div>

      <WizardShell
        steps={steps}
        footer={{
          back: stepIndex > 0 ? () => setParams({ step: STEPS[stepIndex - 1] }) : undefined,
          next
        }}
      >
        {step === "source" ? (
          <div className="flex flex-col gap-3">
            {workspacesQuery.isLoading ? (
              <Skeleton className="h-10 w-full rounded-md" />
            ) : (workspacesQuery.data ?? []).length === 0 ? (
              <PageStateCard
                state="empty"
                title="No workspace to import from"
                description="No other workspace exposes a division grid you can read."
              />
            ) : (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="import-source">Source workspace</Label>
                <Select
                  value={sourceWorkspaceId === null ? undefined : String(sourceWorkspaceId)}
                  onValueChange={(value) =>
                    setParams({ source: value, grid: null, version: null, job: null })
                  }
                >
                  <SelectTrigger id="import-source" className="w-full max-w-md">
                    <SelectValue placeholder="Choose a workspace" />
                  </SelectTrigger>
                  <SelectContent>
                    {(workspacesQuery.data ?? []).map((workspace) => (
                      <SelectItem key={workspace.id} value={String(workspace.id)}>
                        {workspace.name} · {workspace.grids_count} grids, {workspace.versions_count}{" "}
                        versions
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
        ) : null}

        {step === "version" ? (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="import-grid">Grid</Label>
              <Select
                value={sourceGridId === null ? undefined : String(sourceGridId)}
                onValueChange={(value) => setParams({ grid: value, version: null })}
              >
                <SelectTrigger id="import-grid" className="w-full max-w-md">
                  <SelectValue placeholder="Choose a grid" />
                </SelectTrigger>
                <SelectContent>
                  {grids.map((grid) => (
                    <SelectItem key={grid.id} value={String(grid.id)}>
                      {grid.name} · {grid.tiers_count} divisions
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="import-version">Version</Label>
              <Select
                value={sourceVersionId === null ? undefined : String(sourceVersionId)}
                onValueChange={(value) => setParams({ version: value })}
              >
                <SelectTrigger id="import-version" className="w-full max-w-md">
                  <SelectValue
                    placeholder={selectedGrid ? "Choose a version" : "Choose a grid first"}
                  />
                </SelectTrigger>
                <SelectContent>
                  {(selectedGrid?.versions ?? []).map((version) => (
                    <SelectItem key={version.id} value={String(version.id)}>
                      v{version.version} · {version.label} · {version.tiers_count} divisions
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <fieldset className="flex flex-col gap-2">
              <legend className={EYEBROW_CLASS}>What to copy</legend>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="import-icons"
                  checked={includeIcons}
                  onCheckedChange={(checked) => setParams({ icons: checked ? null : "0" })}
                />
                <Label htmlFor="import-icons" className="font-normal">
                  Copy the division crests
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="import-ow"
                  checked={includeOwRanks}
                  onCheckedChange={(checked) => setParams({ ow: checked ? null : "0" })}
                />
                <Label htmlFor="import-ow" className="font-normal">
                  Copy the Overwatch rank mapping
                </Label>
              </div>
            </fieldset>

            {request === null ? (
              <p className="text-sm text-muted-foreground">
                Choose a grid and a version to see what the import would bring in.
              </p>
            ) : preflightQuery.isLoading ? (
              <Skeleton className="h-20 w-full rounded-xl" />
            ) : preflightQuery.isError ? (
              <PageStateCard
                state="error"
                title="Preview unavailable"
                description="The source could not be inspected, so the import is not offered."
                actionLabel="Retry"
                onAction={() => void preflightQuery.refetch()}
              />
            ) : preflightQuery.data ? (
              <div className="rounded-xl border border-border bg-card p-3 text-sm">
                <p className={cn(EYEBROW_CLASS, "font-mono")}>Preview</p>
                <p className="mt-1">
                  {preflightQuery.data.tiers_count} divisions · {preflightQuery.data.mappings_count}{" "}
                  mappings · {preflightQuery.data.assets_to_copy} crests to copy
                </p>
                {preflightQuery.data.conflicts.length > 0 ? (
                  <p className="mt-2">
                    <StatusPill tone="warning">
                      {preflightQuery.data.conflicts.length} to resolve after import
                    </StatusPill>{" "}
                    <span className="text-muted-foreground">
                      Resolved in the draft&apos;s Mappings view, not here.
                    </span>
                  </p>
                ) : null}
                {preflightQuery.data.warnings.length > 0 ? (
                  <ul className="mt-2 flex flex-col gap-1 text-xs text-muted-foreground">
                    {preflightQuery.data.warnings.map((warning) => (
                      <li key={`${warning.grid_slug ?? ""}-${warning.message}`}>
                        {warning.message}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}

        {step === "create" ? (
          <div className="flex flex-col gap-3">
            {job === null ? (
              <Skeleton className="h-20 w-full rounded-xl" />
            ) : job.status === "failed" ? (
              <PageStateCard
                state="error"
                title="Import failed"
                description={
                  job.error ?? "The import job failed and nothing was written into this workspace."
                }
              />
            ) : job.status === "completed" ? (
              <div className="rounded-xl border border-border bg-card p-3 text-sm">
                <p className="font-medium">Draft created</p>
                <p className="mt-1 text-muted-foreground">
                  {job.result?.created_versions ?? 0} versions · {job.result?.created_tiers ?? 0}{" "}
                  divisions · {job.result?.copied_mappings ?? 0} mappings copied. Open it to resolve
                  the mappings against the versions your tournaments still read.
                </p>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                <p className="flex items-center gap-2 text-sm">
                  <Spinner />
                  Copying the grid…
                </p>
                <Progress value={job.progress} />
              </div>
            )}
          </div>
        ) : null}
      </WizardShell>
    </div>
  );
}

function numberParam(searchParams: URLSearchParams | null, key: string): number | null {
  const raw = Number(searchParams?.get(key));
  return Number.isFinite(raw) && raw > 0 ? raw : null;
}
