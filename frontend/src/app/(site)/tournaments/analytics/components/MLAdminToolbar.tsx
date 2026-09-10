"use client";

import React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertCircle, Brain, CheckCircle2, Loader2, PlayCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { useInvalidation } from "@/hooks/useInvalidation";
import { usePermissions } from "@/hooks/usePermissions";
import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import analyticsService from "@/services/analytics.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type {
  AnalyticsJob,
  AnalyticsJobKind,
  AnalyticsJobProgressStage,
  AnalyticsJobRealtimePayload
} from "@/types/analytics.types";

interface MLAdminToolbarProps {
  tournamentId: number;
  workspaceId?: number | null;
}

const TERMINAL_STATUSES = new Set(["succeeded", "failed"]);
type TrainScope = "all" | "current" | "custom";

type JobMutationVariables = {
  kind: AnalyticsJobKind;
  trainingWorkspaceIds?: number[] | null;
};

function statusTone(status: AnalyticsJob["status"]): string {
  switch (status) {
    case "running":
      return "border-[color:color-mix(in_srgb,var(--aqt-blue)_40%,transparent)] text-[color:var(--aqt-blue)]";
    case "succeeded":
      return "border-[color:color-mix(in_srgb,var(--aqt-emerald)_40%,transparent)] text-[color:var(--aqt-emerald)]";
    case "failed":
      return "border-[color:color-mix(in_srgb,var(--aqt-rose)_50%,transparent)] text-[color:var(--aqt-rose)]";
    default:
      return "border-[color:color-mix(in_srgb,var(--aqt-amber)_40%,transparent)] text-[color:var(--aqt-amber)]";
  }
}

function StageRow({ name, stage }: Readonly<{ name: string; stage: AnalyticsJobProgressStage }>) {
  const tone =
    stage.state === "done"
      ? "text-[color:var(--aqt-emerald)]"
      : stage.state === "failed"
        ? "text-[color:var(--aqt-rose)]"
        : "text-[color:var(--aqt-blue)]";

  return (
    <li className="flex items-center justify-between gap-3 text-xs">
      <span className="text-muted-foreground">{name}</span>
      <span className={cn("uppercase tabular-nums", tone)}>{stage.state}</span>
    </li>
  );
}

// Module-scoped so the impure `Date.now()` read is not flagged by the React
// Compiler purity rule (matches the pattern used elsewhere for relative time).
function formatRelative(
  t: ReturnType<typeof useTranslations<never>>,
  iso: string | null | undefined
): string {
  if (!iso) return "-";
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) return t("analytics.job.relativeJustNow");
  if (minutes < 60) return t("analytics.job.relativeMinutes", { count: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 24) return t("analytics.job.relativeHours", { count: hours });
  const days = Math.round(hours / 24);
  return t("analytics.job.relativeDays", { count: days });
}

export default function MLAdminToolbar({ tournamentId, workspaceId }: Readonly<MLAdminToolbarProps>) {
  const t = useTranslations();

  const trainScopeDescription = (scope: TrainScope, selectedCount: number): string => {
    if (scope === "all") return t("analytics.job.sampleAll");
    if (scope === "current") return t("analytics.job.sampleCurrent");
    return t("analytics.job.sampleSelected", { count: selectedCount });
  };

  const { isSuperuser } = usePermissions();
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const [liveJob, setLiveJob] = React.useState<AnalyticsJob | null>(null);
  const [isTrainDialogOpen, setIsTrainDialogOpen] = React.useState(false);
  const [trainScope, setTrainScope] = React.useState<TrainScope>("all");
  const [selectedWorkspaceIds, setSelectedWorkspaceIds] = React.useState<number[]>(() =>
    workspaceId != null ? [workspaceId] : []
  );
  const isLiveJobActive = liveJob != null && !TERMINAL_STATUSES.has(liveJob.status);

  const { data: initialActiveJob } = useQuery({
    queryKey: ["analytics-active-job", workspaceId ?? "global"],
    queryFn: () => analyticsService.getActiveJob(workspaceId),
    refetchInterval: isLiveJobActive ? false : 30_000
  });

  React.useEffect(() => {
    if (initialActiveJob && !liveJob) {
      setLiveJob(initialActiveJob);
    }
  }, [initialActiveJob, liveJob]);

  const { data: refreshedLiveJob } = useQuery({
    queryKey: ["analytics-job", liveJob?.id],
    queryFn: () => analyticsService.getJob(liveJob!.id),
    enabled: isLiveJobActive,
    refetchInterval: isLiveJobActive ? 1_500 : false
  });

  React.useEffect(() => {
    if (!refreshedLiveJob) {
      return;
    }

    setLiveJob((prev) => (prev?.id === refreshedLiveJob.id ? refreshedLiveJob : prev));
  }, [refreshedLiveJob]);

  // The domain topic carries the running job: progress frames have no cache to
  // drop, they drive this toolbar's own state. What a finished job stales
  // (`workspace.analytics_jobs`) arrives separately, on the invalidation topic.
  useRealtimeTopic<AnalyticsJobRealtimePayload>(
    workspaceId != null ? `workspace:${workspaceId}:analytics_jobs` : null,
    (event) => {
      const payload = event.data;
      if (!payload) return;

      setLiveJob((prev) => ({
        id: payload.job_id,
        workspace_id: payload.workspace_id,
        tournament_id: payload.tournament_id,
        requested_by_user_id: prev?.requested_by_user_id ?? null,
        kind: payload.kind,
        status: payload.status,
        algorithms: prev?.algorithms ?? null,
        training_workspace_ids: prev?.training_workspace_ids ?? null,
        progress: payload.progress ?? prev?.progress ?? {},
        error: payload.error ?? null,
        started_at: prev?.started_at ?? null,
        finished_at: TERMINAL_STATUSES.has(payload.status)
          ? new Date().toISOString()
          : (prev?.finished_at ?? null),
        created_at: prev?.created_at ?? new Date().toISOString(),
        updated_at: new Date().toISOString()
      }));
    },
    []
  );

  useInvalidation({ scopeKind: "workspace", scopeId: workspaceId });

  const isActive = isLiveJobActive;
  const trainingWorkspaceIds = React.useMemo(() => {
    if (trainScope === "all") return null;
    if (trainScope === "current") {
      return workspaceId != null ? [workspaceId] : null;
    }
    return selectedWorkspaceIds.length ? selectedWorkspaceIds : [];
  }, [selectedWorkspaceIds, trainScope, workspaceId]);
  const isTrainScopeValid = trainScope !== "custom" || selectedWorkspaceIds.length > 0;

  const toggleWorkspace = (id: number) => {
    setSelectedWorkspaceIds((current) =>
      current.includes(id)
        ? current.filter((workspaceId) => workspaceId !== id)
        : [...current, id].sort((left, right) => left - right)
    );
  };

  const createJobMutation = useMutation({
    mutationFn: ({ kind, trainingWorkspaceIds }: JobMutationVariables) =>
      analyticsService.createJob(
        {
          tournament_id: tournamentId,
          kind,
          ...(kind === "train_ml" ? { training_workspace_ids: trainingWorkspaceIds ?? null } : {})
        },
        workspaceId
      ),
    onSuccess: (job) => {
      setLiveJob(job);
      if (job.kind === "train_ml") {
        setIsTrainDialogOpen(false);
      }
      notify.success(
        job.kind === "train_ml"
          ? t("analytics.job.trainingDispatched")
          : t("analytics.job.recalculationDispatched"),
        {
          description: t("analytics.job.dispatchedDescription", { id: job.id })
        }
      );
    }
  });

  return (
    <div className="w-full space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button
          className="h-10 flex-1 justify-between gap-2"
          onClick={() => createJobMutation.mutate({ kind: "compute" })}
          disabled={isActive || createJobMutation.isPending}
        >
          <span className="truncate">{t("analytics.job.runAnalytics")}</span>
          {createJobMutation.isPending && createJobMutation.variables?.kind === "compute" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <PlayCircle className="h-4 w-4" />
          )}
        </Button>

        {isSuperuser ? (
          <Button
            variant="outline"
            className="h-10 flex-1 justify-between gap-2"
            onClick={() => setIsTrainDialogOpen(true)}
            disabled={isActive || createJobMutation.isPending}
          >
            <span className="truncate">{t("analytics.job.trainMl")}</span>
            {createJobMutation.isPending && createJobMutation.variables?.kind === "train_ml" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Brain className="h-4 w-4" />
            )}
          </Button>
        ) : null}
      </div>

      {isSuperuser ? (
        <Dialog open={isTrainDialogOpen} onOpenChange={setIsTrainDialogOpen}>
          <DialogContent className="sm:max-w-[560px]">
            <DialogHeader>
              <DialogTitle>{t("analytics.job.trainDialogTitle")}</DialogTitle>
              <DialogDescription>{t("analytics.job.trainDialogDescription")}</DialogDescription>
            </DialogHeader>

            <div className="space-y-4">
              <div className="grid gap-2 sm:grid-cols-3">
                <Button
                  type="button"
                  variant={trainScope === "all" ? "default" : "outline"}
                  className="h-auto justify-start px-3 py-3 text-left"
                  onClick={() => setTrainScope("all")}
                >
                  <span>
                    <span className="block font-semibold">{t("analytics.job.scopeAll")}</span>
                    <span className="block text-xs opacity-75">{t("analytics.job.scopeAllHint")}</span>
                  </span>
                </Button>
                <Button
                  type="button"
                  variant={trainScope === "current" ? "default" : "outline"}
                  className="h-auto justify-start px-3 py-3 text-left"
                  onClick={() => {
                    setTrainScope("current");
                    if (workspaceId != null) setSelectedWorkspaceIds([workspaceId]);
                  }}
                  disabled={workspaceId == null}
                >
                  <span>
                    <span className="block font-semibold">{t("analytics.job.scopeCurrent")}</span>
                    <span className="block text-xs opacity-75">{t("analytics.job.scopeCurrentHint")}</span>
                  </span>
                </Button>
                <Button
                  type="button"
                  variant={trainScope === "custom" ? "default" : "outline"}
                  className="h-auto justify-start px-3 py-3 text-left"
                  onClick={() => setTrainScope("custom")}
                >
                  <span>
                    <span className="block font-semibold">{t("analytics.job.scopeSelected")}</span>
                    <span className="block text-xs opacity-75">{t("analytics.job.scopeSelectedHint")}</span>
                  </span>
                </Button>
              </div>

              <div className="rounded-md border bg-background/40 p-3 text-sm">
                <div className="font-medium">{t("analytics.job.trainingSample")}</div>
                <div className="mt-1 text-muted-foreground">
                  {trainScopeDescription(trainScope, selectedWorkspaceIds.length)}
                </div>
              </div>

              {trainScope === "custom" ? (
                <div className="rounded-md border bg-background/30">
                  <div className="border-b px-3 py-2 text-xs font-medium text-muted-foreground">
                    {t("analytics.job.workspaces")}
                  </div>
                  <div className="grid max-h-56 gap-1 overflow-auto p-2">
                    {workspaces.length ? (
                      workspaces.map((workspace) => (
                        <label
                          key={workspace.id}
                          className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm hover:bg-muted/40"
                        >
                          <input
                            type="checkbox"
                            checked={selectedWorkspaceIds.includes(workspace.id)}
                            onChange={() => toggleWorkspace(workspace.id)}
                          />
                          <span className="min-w-0">
                            <span className="block truncate font-medium">{workspace.name}</span>
                            <span className="block truncate text-xs text-muted-foreground">
                              {workspace.slug}
                            </span>
                          </span>
                        </label>
                      ))
                    ) : (
                      <span className="px-2 py-3 text-sm text-muted-foreground">
                        {t("analytics.job.workspaceListNotLoaded")}
                      </span>
                    )}
                  </div>
                </div>
              ) : null}

              {!isTrainScopeValid ? (
                <p className="text-sm text-red-300">{t("analytics.job.selectAtLeastOneWorkspace")}</p>
              ) : null}
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setIsTrainDialogOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                onClick={() =>
                  createJobMutation.mutate({
                    kind: "train_ml",
                    trainingWorkspaceIds
                  })
                }
                disabled={isActive || createJobMutation.isPending || !isTrainScopeValid}
              >
                {createJobMutation.isPending && createJobMutation.variables?.kind === "train_ml" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Brain className="mr-2 h-4 w-4" />
                )}
                {t("analytics.job.startTraining")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}

      {liveJob ? (
        <div
          className={cn(
            "rounded-md border bg-background/40 p-3 text-xs",
            statusTone(liveJob.status)
          )}
        >
          <header className="mb-2 flex items-center justify-between gap-3">
            <span className="flex items-center gap-2 font-medium">
              {liveJob.status === "running" || liveJob.status === "pending" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : liveJob.status === "succeeded" ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : (
                <AlertCircle className="h-3.5 w-3.5" />
              )}
              {t("analytics.job.jobLabel", { id: liveJob.id })} /{" "}
              {liveJob.kind === "train_ml" ? t("analytics.job.trainMl") : t("analytics.job.compute")} /{" "}
              {liveJob.status}
            </span>
            <span className="text-muted-foreground">
              {liveJob.finished_at
                ? t("analytics.job.finishedRelative", { relative: formatRelative(t, liveJob.finished_at) })
                : liveJob.started_at
                  ? t("analytics.job.startedRelative", { relative: formatRelative(t, liveJob.started_at) })
                  : t("analytics.job.createdRelative", { relative: formatRelative(t, liveJob.created_at) })}
            </span>
          </header>

          {Object.keys(liveJob.progress ?? {}).length > 0 ? (
            <ul className="space-y-0.5">
              {Object.entries(liveJob.progress).map(([name, stage]) => (
                <StageRow key={name} name={name} stage={stage} />
              ))}
            </ul>
          ) : null}

          {liveJob.error ? (
            <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap wrap-break-word rounded bg-background/40 p-2 text-label text-red-100">
              {liveJob.error}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
