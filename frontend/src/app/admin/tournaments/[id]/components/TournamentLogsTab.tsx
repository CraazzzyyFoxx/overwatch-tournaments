"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileText,
  FolderInput,
  Loader2,
  RefreshCw,
  RotateCcw,
  Search,
  XCircle
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { useDebounce } from "use-debounce";

import { StatusPill } from "@/components/admin/kit/StatusPill";
import { type Tone } from "@/components/admin/tone";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { InfiniteScrollFooter } from "@/components/ui/infinite-scroll";
import { Skeleton } from "@/components/ui/skeleton";
import { AdminFilterBar } from "@/components/admin/kit/AdminFilterBar";
import { useAdminFilters, type FilterDef } from "@/components/admin/kit/useAdminFilters";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useInvalidation } from "@/hooks/useInvalidation";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type {
  LogProcessingRecord,
  LogProcessingStats,
  LogProcessingStatus
} from "@/types/admin.types";
import type { Encounter } from "@/types/encounter.types";
import { TournamentLogUploadDialog } from "./TournamentLogUploadDialog";
import {
  getTournamentWorkspaceQueryKeys,
  invalidateTournamentWorkspace
} from "./tournamentWorkspace.queryKeys";
import { EmptyNote } from "@/components/admin/kit/EmptyNote";

const PAGE_SIZE = 25;
/**
 * Poll cadence used only while the queue still has work. When nothing is
 * pending the console is driven by the `workspace.logs` invalidation (parser
 * publishes it on every completion), so an idle tab costs no requests — the old
 * console polled every 10s forever.
 */
const ACTIVE_QUEUE_POLL_MS = 10_000;

type LogFilter = LogProcessingStatus;

const STATUS_META: Record<LogProcessingStatus, { label: string; icon: LucideIcon; tone: Tone }> = {
  pending: { label: "Queued", icon: Clock3, tone: "neutral" },
  processing: { label: "Processing", icon: Loader2, tone: "info" },
  done: { label: "Processed", icon: CheckCircle2, tone: "success" },
  failed: { label: "Failed", icon: XCircle, tone: "danger" }
};

/** Chip order is scan order: the states that need action come first. */
const LOG_FILTERS: LogFilter[] = ["failed", "processing", "pending", "done"];

const SOURCE_LABELS: Record<LogProcessingRecord["source"], string> = {
  upload: "Upload",
  discord: "Discord",
  manual: "Manual"
};

interface TournamentLogsTabProps {
  /** `null` = every tournament in the workspace. */
  tournamentId: number | null;
  workspaceId: number | null;
  encounters: Encounter[];
  canUploadLogs: boolean;
  enabled: boolean;
}

function getLogFileName(filename: string) {
  return filename.split(/[\\/]/).at(-1) ?? filename;
}

function formatDuration(record: LogProcessingRecord) {
  if (!record.started_at || !record.finished_at) {
    return record.status === "processing" ? "running" : "-";
  }

  const durationMs = new Date(record.finished_at).getTime() - new Date(record.started_at).getTime();
  if (!Number.isFinite(durationMs) || durationMs < 0) return "-";
  return `${(durationMs / 1000).toFixed(1)}s`;
}

/** Matches `formatSyncTime` in ChallongeIntegrationSection so both admin logs read alike. */
function formatLogTime(value: string) {
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function getErrorSummary(errorMessage: string | null) {
  if (!errorMessage) return null;

  const codeMatch = errorMessage.match(/['"]code['"]:\s*['"]([^'"]+)['"]/);
  const statusMatch = errorMessage.match(/^(\d{3})/);
  const code = codeMatch?.[1]?.replaceAll("_", " ");

  if (code) {
    const formattedCode = code.charAt(0).toUpperCase() + code.slice(1);
    return statusMatch ? `${statusMatch[1]} · ${formattedCode}` : formattedCode;
  }

  return errorMessage.replace(/^(\d{3}:\s*)?/, "").slice(0, 120);
}

function LogStatusBadge({ status }: Readonly<{ status: LogProcessingStatus }>) {
  const meta = STATUS_META[status];
  const Icon = meta.icon;

  return (
    <StatusPill tone={meta.tone} className="px-1.5">
      <Icon className={cn("size-3", status === "processing" && "animate-spin")} aria-hidden />
      {meta.label}
    </StatusPill>
  );
}

/** Counts come from the server aggregate, so a chip shows its real size. */
function getFilterCount(filter: LogFilter, stats: LogProcessingStats | undefined) {
  return stats ? stats[filter] : undefined;
}

export function TournamentLogsTab({
  tournamentId,
  workspaceId,
  encounters,
  canUploadLogs,
  enabled
}: Readonly<TournamentLogsTabProps>) {
  const queryClient = useQueryClient();
  // Scoped to a tournament inside the hub, to the workspace on the
  // cross-tournament browser. Both keys are what realtime and the tab badge
  // address, so nothing here invents a key of its own.
  const historyKey =
    tournamentId != null
      ? getTournamentWorkspaceQueryKeys(tournamentId).logHistory
      : (["admin", "workspace", workspaceId, "log-history"] as const);
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch] = useDebounce(searchInput, 300);
  const searchTerm = debouncedSearch.trim();

  const statsQuery = useQuery({
    queryKey: [...historyKey, "stats"],
    queryFn: () =>
      tournamentId != null
        ? adminService.getLogStats(tournamentId)
        : adminService.getLogStats(undefined, { workspaceId }),
    enabled
  });
  const stats = statsQuery.data;
  const queueActive = stats != null && stats.pending + stats.processing > 0;
  const pollInterval = enabled && queueActive ? ACTIVE_QUEUE_POLL_MS : false;

  // One single-select chip instead of a five-button toggle group, and the
  // choice now lives in the URL: a "show me the failures" link is shareable,
  // which component state could never be.
  const defs = useMemo<FilterDef[]>(
    () => [
      {
        key: "status",
        label: "Status",
        kind: "single",
        options: LOG_FILTERS.map((filter) => ({
          value: filter,
          label: STATUS_META[filter].label,
          count: getFilterCount(filter, stats)
        }))
      }
    ],
    [stats]
  );
  const filters = useAdminFilters(defs);
  const rawStatus = String(filters.values.status ?? "");
  const statusFilter = (LOG_FILTERS as readonly string[]).includes(rawStatus)
    ? (rawStatus as LogFilter)
    : null;

  const historyQuery = useInfiniteQuery({
    queryKey: [...historyKey, "list", statusFilter ?? "all", searchTerm],
    queryFn: ({ pageParam }) =>
      adminService.getLogHistory(tournamentId ?? undefined, {
        limit: PAGE_SIZE,
        offset: pageParam,
        status: statusFilter ?? undefined,
        search: searchTerm,
        ...(tournamentId == null && { workspaceId })
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((count, page) => count + page.items.length, 0);
      // A page shorter than requested means the tail; stop even if `total`
      // grew underneath us while the operator was scrolling.
      if (lastPage.items.length < PAGE_SIZE || loaded >= lastPage.total) return undefined;
      return loaded;
    },
    enabled,
    refetchInterval: pollInterval
  });

  // Offset paging over a list that grows at the head can repeat a record across
  // page boundaries. Keying by id collapses those: position comes from where the
  // record first appeared, the value from the freshest page carrying it.
  const records = Array.from(
    new Map(
      (historyQuery.data?.pages ?? [])
        .flatMap((page) => page.items)
        .map((record) => [record.id, record] as const)
    ).values()
  );
  const matchedTotal = historyQuery.data?.pages[0]?.total;
  const loadedFailures = records.filter((record) => record.status === "failed");
  const hasActiveFilter = statusFilter != null || searchTerm.length > 0;

  const refreshAll = () => {
    void statsQuery.refetch();
    void historyQuery.refetch();
  };

  // Parser completions arrive as `workspace.logs`, which stales exactly this
  // console's history key — and the stats query keyed under it. `tournamentId`
  // is what tells the registry which of the two variants of that key exists
  // here: the signal is workspace-wide, the console is mounted per tournament.
  useInvalidation({
    scopeKind: "workspace",
    scopeId: enabled ? workspaceId : null,
    tournamentId
  });

  const retryLogMutation = useMutation({
    mutationFn: (recordId: number) => adminService.retryLogRecord(recordId),
    onSuccess: () => {
      notify.success("Log retry queued");
      refreshAll();
    }
  });

  const retryFailuresMutation = useMutation({
    mutationFn: async (recordIds: number[]) => {
      const results = await Promise.allSettled(
        recordIds.map((recordId) => adminService.retryLogRecord(recordId))
      );
      return results.filter((result) => result.status === "rejected").length;
    },
    onSuccess: (failedCount, recordIds) => {
      const queued = recordIds.length - failedCount;
      if (failedCount > 0) {
        notify.error(`Queued ${queued} of ${recordIds.length} logs`, {
          description: `${failedCount} could not be queued. Retry them individually.`
        });
      } else {
        notify.success(`Queued ${queued} logs for retry`);
      }
      refreshAll();
    }
  });

  const processAllLogsMutation = useMutation({
    mutationFn: () => adminService.processAllTournamentLogs(tournamentId!),
    onSuccess: () => {
      notify.success("Processing queued for all S3 logs");
      refreshAll();
    }
  });

  const isRetrying = (recordId: number) =>
    (retryLogMutation.isPending && retryLogMutation.variables === recordId) ||
    (retryFailuresMutation.isPending && retryFailuresMutation.variables?.includes(recordId));

  return (
    <TooltipProvider>
      <Card className="border-border/40">
        <CardHeader className="gap-2 pb-3">
          <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <FolderInput className="size-4 shrink-0 text-primary" aria-hidden />
                <CardTitle asChild className="text-base font-semibold">
                  <h2>Log processing</h2>
                </CardTitle>
              </div>
              <CardDescription className="mt-1 text-pretty">
                Track uploaded and Discord/S3 match logs, isolate failures, and queue retries.
                Stalled logs are requeued automatically.
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-1">
              {canUploadLogs && tournamentId != null ? (
                <TournamentLogUploadDialog
                  tournamentId={tournamentId}
                  encounters={encounters}
                  onUploaded={() => {
                    invalidateTournamentWorkspace(queryClient, tournamentId);
                    refreshAll();
                  }}
                  trigger={
                    <Button variant="outline" size="sm" className="h-8">
                      Upload logs
                    </Button>
                  }
                />
              ) : null}
              {/* Both endpoints are per tournament, so the workspace-wide
                  console reads without offering them. */}
              {tournamentId != null ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8"
                  disabled={processAllLogsMutation.isPending}
                  onClick={() => processAllLogsMutation.mutate()}
                >
                  {processAllLogsMutation.isPending ? (
                    <Loader2 className="animate-spin" aria-hidden />
                  ) : null}
                  Process S3 logs
                </Button>
              ) : null}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-8"
                    aria-label="Refresh log processing"
                    onClick={refreshAll}
                    disabled={historyQuery.isFetching || statsQuery.isFetching}
                  >
                    <RefreshCw
                      className={cn(
                        (historyQuery.isFetching || statsQuery.isFetching) && "animate-spin"
                      )}
                      aria-hidden
                    />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Refresh log processing</TooltipContent>
              </Tooltip>
            </div>
          </div>
        </CardHeader>

        <CardContent className="flex flex-col gap-3 p-4 pt-0">
          <AdminFilterBar
            defs={defs}
            filters={filters}
            search={{
              placeholder: "file, error, uploader, encounter",
              value: searchInput,
              onChange: setSearchInput
            }}
            trailing={
              stats ? (
                <p className="hidden shrink-0 text-xs text-muted-foreground sm:block">
                  <span className="tabular-nums text-foreground/80">
                    {stats.total.toLocaleString()}
                  </span>
                  {" logs · avg "}
                  <span className="tabular-nums text-foreground/80">
                    {stats.avg_duration_seconds != null
                      ? `${stats.avg_duration_seconds.toFixed(1)}s`
                      : "-"}
                  </span>
                  {stats.last_created_at ? (
                    <>
                      {" · newest "}
                      <span className="tabular-nums text-foreground/80">
                        {formatLogTime(stats.last_created_at)}
                      </span>
                    </>
                  ) : null}
                </p>
              ) : null
            }
          />

          {stats && stats.failed > 0 ? (
            <div className="flex flex-col gap-2 rounded-lg border border-danger/25 bg-danger/5 px-3 py-2 text-xs sm:flex-row sm:items-center sm:justify-between">
              <p className="min-w-0 text-danger">
                {stats.failed.toLocaleString()} log{stats.failed === 1 ? "" : "s"} failed to process
              </p>
              <div className="flex shrink-0 flex-wrap items-center gap-1">
                {statusFilter !== "failed" ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={() => filters.set("status", "failed")}
                  >
                    Show failed
                  </Button>
                ) : null}
                {loadedFailures.length > 0 ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs"
                    disabled={retryFailuresMutation.isPending}
                    onClick={() =>
                      retryFailuresMutation.mutate(loadedFailures.map((record) => record.id))
                    }
                  >
                    {retryFailuresMutation.isPending ? (
                      <Loader2 className="animate-spin" aria-hidden />
                    ) : (
                      <RotateCcw aria-hidden />
                    )}
                    Retry {loadedFailures.length} loaded
                  </Button>
                ) : null}
              </div>
            </div>
          ) : null}

          {historyQuery.isPending ? (
            <div className="flex flex-col gap-1.5" aria-hidden>
              <Skeleton className="h-11 w-full" />
              <Skeleton className="h-11 w-full" />
              <Skeleton className="h-11 w-full" />
              <Skeleton className="h-11 w-full" />
            </div>
          ) : records.length === 0 ? (
            hasActiveFilter ? (
              <EmptyNote
                icon={Search}
                title={searchTerm ? `No logs match “${searchTerm}”` : "No logs in this status"}
                action={
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      filters.clear();
                      setSearchInput("");
                    }}
                  >
                    Clear filters
                  </Button>
                }
              >
                Search covers every log in this scope, not just the loaded rows.
              </EmptyNote>
            ) : (
              <EmptyNote
                icon={FileText}
                title={
                  tournamentId != null
                    ? "No logs for this tournament yet"
                    : "No logs in this workspace yet"
                }
              >
                Upload log files or process stored S3 logs to populate this console.
              </EmptyNote>
            )
          ) : (
            <>
              <ul className="divide-y divide-border/30 overflow-hidden rounded-lg border border-border/40">
                {records.map((record) => {
                  const fileName = getLogFileName(record.filename);
                  const errorSummary = getErrorSummary(record.error_message);
                  const retrying = isRetrying(record.id);
                  // "Queued"/"Processing" rows go stale when the worker drops
                  // their queue message; the reaper requeues them on its own
                  // schedule, this is the operator's shortcut past the wait.
                  const canRequeue = record.status !== "done";
                  const requeueLabel = record.status === "failed" ? "Retry log" : "Requeue log";

                  return (
                    <li
                      key={record.id}
                      className={cn(
                        "px-3 py-1.5 transition-colors hover:bg-accent/20",
                        record.status === "failed" && "bg-danger/5 hover:bg-danger/10"
                      )}
                    >
                      {/*
                        One line per record. The uploader and source used to sit
                        on a second line under every filename, which doubled the
                        row height to repeat the same two values 25 times; both
                        now ride the row's tooltip.
                      */}
                      <div
                        className="flex flex-wrap items-center gap-x-3 gap-y-0.5"
                        title={`${record.filename}\n${SOURCE_LABELS[record.source]} by ${record.uploader_name ?? "unknown uploader"}${record.attempts > 1 ? `\n${record.attempts} processing attempts` : ""}`}
                      >
                        <p className="min-w-0 flex-1 basis-48 truncate font-mono text-xs">
                          {fileName}
                        </p>
                        <p className="min-w-0 flex-1 basis-40 truncate text-xs text-muted-foreground">
                          {record.attached_encounter_name ?? "Not attached"}
                        </p>
                        <div className="flex w-28 shrink-0 items-center gap-1.5">
                          <LogStatusBadge status={record.status} />
                          {record.attempts > 1 ? (
                            <span className="text-xs tabular-nums text-muted-foreground">
                              ×{record.attempts}
                            </span>
                          ) : null}
                        </div>
                        <p className="w-28 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                          {formatLogTime(record.created_at)}
                        </p>
                        <p className="w-14 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                          {formatDuration(record)}
                        </p>
                        <div className="flex w-8 shrink-0 justify-end">
                          {canRequeue ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="size-8"
                                  aria-label={`${requeueLabel} ${fileName}`}
                                  disabled={retrying}
                                  onClick={() => retryLogMutation.mutate(record.id)}
                                >
                                  {retrying ? (
                                    <Loader2 className="animate-spin" aria-hidden />
                                  ) : (
                                    <RotateCcw aria-hidden />
                                  )}
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>{requeueLabel}</TooltipContent>
                            </Tooltip>
                          ) : null}
                        </div>
                      </div>

                      {errorSummary ? (
                        <details className="group mt-1.5">
                          <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded text-xs text-danger focus-visible:outline-2 focus-visible:outline-offset-2">
                            <ChevronRight
                              className="size-3 transition-transform group-open:rotate-90"
                              aria-hidden
                            />
                            {errorSummary}
                          </summary>
                          <pre
                            tabIndex={0}
                            className="mt-1.5 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/20 p-2 text-xs text-muted-foreground"
                          >
                            {record.error_message}
                          </pre>
                        </details>
                      ) : null}
                    </li>
                  );
                })}
              </ul>

              <InfiniteScrollFooter
                loaded={records.length}
                total={matchedTotal}
                unit="logs"
                hasNextPage={historyQuery.hasNextPage}
                isFetchingNextPage={historyQuery.isFetchingNextPage}
                fetchNextPage={historyQuery.fetchNextPage}
                isError={historyQuery.isError}
              />
            </>
          )}
        </CardContent>
      </Card>
    </TooltipProvider>
  );
}
