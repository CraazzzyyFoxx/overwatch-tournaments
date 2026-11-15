"use client";

import React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Brain, CheckCircle2, PlayCircle, XCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Checkbox } from "@craazzzyyfoxx/admin-kit/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@craazzzyyfoxx/admin-kit/ui/dialog";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { useInvalidation } from "@/hooks/useInvalidation";
import { useMinuteClock } from "@/hooks/useMinuteClock";
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
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";
import { analyticsQueryKeys } from "@/lib/analytics/query-keys";

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

const TRAIN_SCOPES = [
  { value: "all", label: "analytics.job.scopeAll", hint: "analytics.job.scopeAllHint" },
  { value: "current", label: "analytics.job.scopeCurrent", hint: "analytics.job.scopeCurrentHint" },
  { value: "custom", label: "analytics.job.scopeSelected", hint: "analytics.job.scopeSelectedHint" }
] as const;

const STAGE_TONE: Record<AnalyticsJobProgressStage["state"], string> = {
  running: "text-[color:var(--aqt-fg)]",
  done: "text-[color:var(--aqt-up)]",
  failed: "text-[color:var(--aqt-rose)]"
};

export default function MLAdminToolbar({ tournamentId, workspaceId }: Readonly<MLAdminToolbarProps>) {
  const t = useTranslations();
  const format = useFormatter();
  const now = useMinuteClock();

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
    queryKey: analyticsQueryKeys.activeJob(workspaceId ?? "global"),
    queryFn: () => analyticsService.getActiveJob(workspaceId),
    refetchInterval: isLiveJobActive ? false : 30_000
  });

  // Adopted during render rather than in an effect, so a job already running is
  // never painted as "no job" first.
  if (initialActiveJob && !liveJob) {
    setLiveJob(initialActiveJob);
  }

  const { data: refreshedLiveJob } = useQuery({
    queryKey: analyticsQueryKeys.job(liveJob?.id),
    queryFn: () => analyticsService.getJob(liveJob!.id),
    enabled: isLiveJobActive,
    refetchInterval: isLiveJobActive ? 1_500 : false
  });

  // Each poll result replaces the job it was asked about, once per result; a
  // different job that took its place in between stays. Adjusted during render.
  const [adoptedRefresh, setAdoptedRefresh] = React.useState(refreshedLiveJob);
  if (refreshedLiveJob !== adoptedRefresh) {
    setAdoptedRefresh(refreshedLiveJob);
    if (refreshedLiveJob) {
      setLiveJob((prev) => (prev?.id === refreshedLiveJob.id ? refreshedLiveJob : prev));
    }
  }

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

  const fieldId = React.useId();
  const isComputePending = createJobMutation.isPending && createJobMutation.variables?.kind === "compute";
  const isTrainPending = createJobMutation.isPending && createJobMutation.variables?.kind === "train_ml";
  const stages = Object.entries(liveJob?.progress ?? {});
  const stageLabel = (name: string) => {
    const key = `analytics.job.stage.${name}` as "analytics.job.stage.train";
    return t.has(key) ? t(key) : t("analytics.job.stage.other");
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Button
          size="lg"
          onClick={() => createJobMutation.mutate({ kind: "compute" })}
          disabled={isActive || createJobMutation.isPending}
        >
          {isComputePending ? <Spinner /> : <PlayCircle aria-hidden />}
          {t("analytics.job.runAnalytics")}
        </Button>

        {isSuperuser ? (
          <Button
            size="lg"
            variant="outline"
            onClick={() => setIsTrainDialogOpen(true)}
            disabled={isActive || createJobMutation.isPending}
          >
            {isTrainPending ? <Spinner /> : <Brain aria-hidden />}
            {t("analytics.job.trainMl")}
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
              <div className="space-y-3">
                <Eyebrow as="p" id={`${fieldId}-scope`}>
                  {t("analytics.job.trainingSample")}
                </Eyebrow>
                <RadioGroup
                  aria-labelledby={`${fieldId}-scope`}
                  value={trainScope}
                  onValueChange={(value) => {
                    const scope = value as TrainScope;
                    setTrainScope(scope);
                    if (scope === "current" && workspaceId != null) setSelectedWorkspaceIds([workspaceId]);
                  }}
                >
                  {TRAIN_SCOPES.map((scope) => {
                    const id = `${fieldId}-scope-${scope.value}`;
                    const disabled = scope.value === "current" && workspaceId == null;
                    return (
                      <div key={scope.value} className="flex items-start gap-3">
                        <RadioGroupItem
                          id={id}
                          value={scope.value}
                          disabled={disabled}
                          aria-describedby={`${id}-hint`}
                        />
                        <div className={cn("grid gap-1", disabled && "opacity-50")}>
                          <Label htmlFor={id}>{t(scope.label)}</Label>
                          <p id={`${id}-hint`} className="text-caption text-[color:var(--aqt-fg-muted)]">
                            {t(scope.hint)}
                          </p>
                        </div>
                      </div>
                    );
                  })}
                </RadioGroup>
              </div>

              {trainScope === "custom" ? (
                <div
                  role="group"
                  aria-labelledby={`${fieldId}-workspaces`}
                  className="space-y-3 border-t border-[color:var(--aqt-border)] pt-4"
                >
                  <Eyebrow as="p" id={`${fieldId}-workspaces`}>
                    {t("analytics.job.workspaces")}
                  </Eyebrow>
                  {workspaces.length ? (
                    <div className="-m-1 grid max-h-56 gap-3 overflow-auto p-1">
                      {workspaces.map((workspace) => {
                        const id = `${fieldId}-workspace-${workspace.id}`;
                        return (
                          <div key={workspace.id} className="flex items-start gap-3">
                            <Checkbox
                              id={id}
                              checked={selectedWorkspaceIds.includes(workspace.id)}
                              onCheckedChange={() => toggleWorkspace(workspace.id)}
                              aria-describedby={`${id}-slug`}
                            />
                            <div className="grid min-w-0 gap-1 wrap-break-word">
                              <Label htmlFor={id}>{workspace.name}</Label>
                              <p id={`${id}-slug`} className="text-caption text-[color:var(--aqt-fg-muted)]">
                                {workspace.slug}
                              </p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-body text-[color:var(--aqt-fg-muted)]">
                      {t("analytics.job.workspaceListNotLoaded")}
                    </p>
                  )}
                </div>
              ) : null}

              {!isTrainScopeValid ? (
                <p className="text-body text-[color:var(--aqt-rose)]">
                  {t("analytics.job.selectAtLeastOneWorkspace")}
                </p>
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
                {isTrainPending ? <Spinner /> : <Brain aria-hidden />}
                {t("analytics.job.startTraining")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}

      {liveJob ? (
        <div className="space-y-2 border-t border-[color:var(--aqt-border)] pt-4">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-[color:var(--aqt-fg-muted)]">
            <span className="flex items-center gap-2 text-body text-[color:var(--aqt-fg)]">
              {liveJob.status === "succeeded" ? (
                <CheckCircle2 aria-hidden className="size-4 text-[color:var(--aqt-up)]" />
              ) : liveJob.status === "failed" ? (
                <XCircle aria-hidden className="size-4 text-[color:var(--aqt-rose)]" />
              ) : (
                <Spinner />
              )}
              {t(`analytics.job.status.${liveJob.status}`)}
            </span>
            <span aria-hidden className="text-[color:var(--aqt-fg-dim)]">
              ·
            </span>
            <span>{liveJob.kind === "train_ml" ? t("analytics.job.trainMl") : t("analytics.job.compute")}</span>
            <span aria-hidden className="text-[color:var(--aqt-fg-dim)]">
              ·
            </span>
            <span>{t("analytics.job.jobLabel", { id: liveJob.id })}</span>
            {now !== null ? (
              <>
                <span aria-hidden className="text-[color:var(--aqt-fg-dim)]">
                  ·
                </span>
                <span>
                  {liveJob.finished_at
                    ? t("analytics.job.finishedRelative", {
                        relative: format.relativeTime(new Date(liveJob.finished_at), now)
                      })
                    : liveJob.started_at
                      ? t("analytics.job.startedRelative", {
                          relative: format.relativeTime(new Date(liveJob.started_at), now)
                        })
                      : t("analytics.job.createdRelative", {
                          relative: format.relativeTime(new Date(liveJob.created_at), now)
                        })}
                </span>
              </>
            ) : null}
          </p>

          {stages.length > 0 ? (
            <ul className="max-w-sm space-y-1 pl-6 text-caption">
              {stages.map(([name, stage]) => (
                <li key={name} className="flex items-center justify-between gap-3">
                  <span className="text-[color:var(--aqt-fg-muted)]">{stageLabel(name)}</span>
                  <span className={STAGE_TONE[stage.state]}>{t(`analytics.job.stageState.${stage.state}`)}</span>
                </li>
              ))}
            </ul>
          ) : null}

          {liveJob.error ? (
            <pre className="ml-6 max-h-32 overflow-auto whitespace-pre-wrap wrap-break-word rounded-md bg-[color:var(--aqt-card-2)] p-2 text-label text-[color:var(--aqt-fg-muted)]">
              {liveJob.error}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
