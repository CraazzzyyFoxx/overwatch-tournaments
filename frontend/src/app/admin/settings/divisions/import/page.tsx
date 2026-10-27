"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { WizardShell, type WizardStep } from "@/components/kit/WizardShell";
import { Card } from "@/components/ui/card";
import { eyebrowClass } from "@/components/ui/eyebrow";
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
import workspaceService from "@/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { DivisionGridMarketplaceImportRequest } from "@/types/workspace.types";
import { divisionGridQueryKeys } from "@/lib/divisions/query-keys";

const STEPS = ["source", "version", "create"] as const;
type StepKey = (typeof STEPS)[number];

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
  const t = useTranslations("adminSettings.divisionsImport");
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
  const includeNativeRanks = searchParams?.get("ow") !== "0";

  const workspacesQuery = useQuery({
    queryKey: divisionGridQueryKeys.importWorkspaces(workspaceId),
    queryFn: () => workspaceService.getDivisionGridMarketplaceWorkspaces(workspaceId!),
    enabled: canImport
  });

  const gridsQuery = useQuery({
    queryKey: divisionGridQueryKeys.importGrids(workspaceId, sourceWorkspaceId),
    queryFn: () => workspaceService.getDivisionGridMarketplace(workspaceId!, sourceWorkspaceId!),
    enabled: canImport && sourceWorkspaceId !== null
  });
  const grids = gridsQuery.data ?? [];
  const selectedGrid = grids.find((grid) => grid.id === sourceGridId) ?? null;

  const request: DivisionGridMarketplaceImportRequest | null =
    sourceWorkspaceId === null || sourceGridId === null || sourceVersionId === null
      ? null
      : {
          source_workspace_id: sourceWorkspaceId,
          source_grid_id: sourceGridId,
          source_version_id: sourceVersionId,
          include_icons: includeIcons,
          include_native_rank_mappings: includeNativeRanks
        };

  const preflightQuery = useQuery({
    queryKey: divisionGridQueryKeys.importPreflight(workspaceId, request),
    queryFn: () => workspaceService.preflightDivisionGridMarketplace(workspaceId!, request!),
    enabled: canImport && request !== null
  });

  const jobQuery = useQuery({
    queryKey: divisionGridQueryKeys.importJob(workspaceId, jobId),
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
    // The import result names the target grid, not its game; the grid id identifies the entry.
    queryKey: divisionGridQueryKeys.versions(workspaceId, null, importedGridId),
    queryFn: () => workspaceService.getDivisionGridVersions(workspaceId!, importedGridId!),
    enabled: canImport && importedGridId !== null
  });

  const importMutation = useMutation({
    mutationFn: () => workspaceService.importDivisionGridMarketplace(workspaceId!, request!),
    onSuccess: (started) => setParams({ step: "create", job: String(started.id) }),
    onError: (error) =>
      notify.error(t("errors.start"), {
        description: t("errors.startDescription", {
          reason: error instanceof Error ? error.message : t("errors.requestFailed")
        })
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
        title={t("noWorkspace.title")}
        description={t("noWorkspace.description")}
      />
    );
  }

  if (!canImport) {
    return (
      <PageStateCard
        state="not-found"
        title={t("unavailable.title")}
        description={t("unavailable.description")}
      />
    );
  }

  const stepIndex = STEPS.indexOf(step);
  const steps: WizardStep[] = STEPS.map((key, index) => ({
    key,
    label: t(`steps.${key}`),
    state: index === stepIndex ? "current" : index < stepIndex ? "done" : "todo"
  }));

  const next =
    step === "source"
      ? {
          label: t("continue"),
          disabled: sourceWorkspaceId === null,
          onClick: () => setParams({ step: "version" })
        }
      : step === "version"
        ? {
            label: t("createDraft"),
            disabled: request === null || importMutation.isPending,
            onClick: () => importMutation.mutate()
          }
        : {
            label: t("openDraft"),
            disabled: importedVersion === null,
            onClick: () =>
              router.push(`/admin/settings/divisions/v/${importedVersion!.id}?tab=mappings`)
          };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="font-display text-lg font-semibold">{t("title")}</h2>
        <p className="text-sm text-muted-foreground">
          {t("description")}
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
                title={t("noSource.title")}
                description={t("noSource.description")}
              />
            ) : (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="import-source">{t("sourceWorkspace")}</Label>
                <Select
                  value={sourceWorkspaceId === null ? undefined : String(sourceWorkspaceId)}
                  onValueChange={(value) =>
                    setParams({ source: value, grid: null, version: null, job: null })
                  }
                >
                  <SelectTrigger id="import-source" className="w-full max-w-md">
                    <SelectValue placeholder={t("chooseWorkspace")} />
                  </SelectTrigger>
                  <SelectContent>
                    {(workspacesQuery.data ?? []).map((workspace) => (
                      <SelectItem key={workspace.id} value={String(workspace.id)}>
                        {t("workspaceOption", {
                          name: workspace.name,
                          grids: workspace.grids_count,
                          versions: workspace.versions_count
                        })}
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
              <Label htmlFor="import-grid">{t("grid")}</Label>
              <Select
                value={sourceGridId === null ? undefined : String(sourceGridId)}
                onValueChange={(value) => setParams({ grid: value, version: null })}
              >
                <SelectTrigger id="import-grid" className="w-full max-w-md">
                <SelectValue placeholder={t("chooseGrid")} />
                </SelectTrigger>
                <SelectContent>
                  {grids.map((grid) => (
                    <SelectItem key={grid.id} value={String(grid.id)}>
                      {t("gridOption", { name: grid.name, count: grid.tiers_count })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="import-version">{t("version")}</Label>
              <Select
                value={sourceVersionId === null ? undefined : String(sourceVersionId)}
                onValueChange={(value) => setParams({ version: value })}
              >
                <SelectTrigger id="import-version" className="w-full max-w-md">
                  <SelectValue
                    placeholder={selectedGrid ? t("chooseVersion") : t("chooseGridFirst")}
                  />
                </SelectTrigger>
                <SelectContent>
                  {(selectedGrid?.versions ?? []).map((version) => (
                    <SelectItem key={version.id} value={String(version.id)}>
                      {t("versionOption", {
                        version: version.version,
                        label: version.label,
                        count: version.tiers_count
                      })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <fieldset className="flex flex-col gap-2">
              <legend className={eyebrowClass("muted")}>{t("whatToCopy")}</legend>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="import-icons"
                  checked={includeIcons}
                  onCheckedChange={(checked) => setParams({ icons: checked ? null : "0" })}
                />
                <Label htmlFor="import-icons" className="font-normal">
                  {t("copyCrests")}
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="import-ow"
                  checked={includeNativeRanks}
                  onCheckedChange={(checked) => setParams({ ow: checked ? null : "0" })}
                />
                <Label htmlFor="import-ow" className="font-normal">
                  {t("copyOwMapping")}
                </Label>
              </div>
            </fieldset>

            {request === null ? (
              <p className="text-sm text-muted-foreground">
                {t("chooseToPreview")}
              </p>
            ) : preflightQuery.isLoading ? (
              <Skeleton className="h-20 w-full rounded-xl" />
            ) : preflightQuery.isError ? (
              <PageStateCard
                state="error"
                title={t("previewUnavailable.title")}
                description={t("previewUnavailable.description")}
                actionLabel={t("retry")}
                onAction={() => void preflightQuery.refetch()}
              />
            ) : preflightQuery.data ? (
              <Card className="p-3 text-sm">
                <p className={eyebrowClass("muted")}>{t("preview")}</p>
                <p className="mt-1">
                  {t("previewSummary", { divisions: preflightQuery.data.tiers_count, mappings: preflightQuery.data.mappings_count, crests: preflightQuery.data.assets_to_copy })}
                </p>
                {preflightQuery.data.conflicts.length > 0 ? (
                  <p className="mt-2 text-muted-foreground">
                    {t("conflicts", { count: preflightQuery.data.conflicts.length })}
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
              </Card>
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
                title={t("importFailed")}
                description={
                  job.error ?? t("importFailedDescription")
                }
              />
            ) : job.status === "completed" ? (
              <Card className="p-3 text-sm">
                <p className="font-medium">{t("draftCreated")}</p>
                <p className="mt-1 text-muted-foreground">
                  {t("createdSummary", { versions: job.result?.created_versions ?? 0, divisions: job.result?.created_tiers ?? 0, mappings: job.result?.copied_mappings ?? 0 })}
                </p>
              </Card>
            ) : (
              <div className="flex flex-col gap-2">
                <p className="text-sm">{t("copying")}</p>
                <Progress value={job.progress} aria-label={t("copying")} />
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
