"use client";

import { useIsFetching, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  CheckCircle2,
  ChevronRight,
  Clock3,
  FolderInput,
  Link2,
  Loader2,
  RefreshCw,
  RotateCcw,
  XCircle
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useFormatter } from "@/lib/datetime/client";

import { columnMeta, createKebabColumn, DataTable } from "@/components/data-table";
import { StatusPill } from "@/components/kit/StatusPill";
import { type Tone } from "@/components/kit/tone";
import type { DateFormatter } from "@/components/kit/format-time";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import SearchableImageSelect from "@/components/ui/searchable-image-select";
import { encounterScopeLabel } from "@/components/admin/encounters/EncounterCells";
import { bracketRoundLabelEn, UNKNOWN_ROUND_SHAPE } from "@/lib/bracket/round-name";
import { FilterBar } from "@/components/kit/FilterBar";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
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
import { TournamentLogUploadDialog } from "@/components/logs/TournamentLogUploadDialog";
import {
  getTournamentWorkspaceQueryKeys,
  invalidateTournamentWorkspace
} from "@/lib/tournament/workspace-query-keys";
import { Spinner } from "@/components/ui/spinner";
import { adminQueryKeys } from "@/lib/admin/query-keys";

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
function formatLogTime(format: DateFormatter, value: string) {
  return format.dateTime(new Date(value), {
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

/** Two encounters of one pair share a name, so the stage and round tell them apart. */
function encounterOptionLabel(encounter: Encounter) {
  return `${encounter.name} · ${encounterScopeLabel(encounter)} · ${bracketRoundLabelEn(encounter.round, UNKNOWN_ROUND_SHAPE)}`;
}

function AttachLogDialog({
  record,
  encounters,
  isPending,
  onAttach,
  onClose
}: Readonly<{
  record: LogProcessingRecord | null;
  encounters: Encounter[];
  isPending: boolean;
  onAttach: (encounterId: number) => void;
  onClose: () => void;
}>) {
  const [picked, setPicked] = useState<string | undefined>(undefined);
  const value =
    picked ?? (record?.attached_encounter_id != null ? String(record.attached_encounter_id) : undefined);

  return (
    <Dialog
      open={record != null}
      onOpenChange={(open) => {
        if (open) return;
        setPicked(undefined);
        onClose();
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Attach log to encounter</DialogTitle>
          <DialogDescription className="break-all">
            {record ? getLogFileName(record.filename) : null} is reprocessed into the encounter you
            pick. Its teams must be the ones the log shows.
          </DialogDescription>
        </DialogHeader>
        <SearchableImageSelect
          value={value}
          onValueChange={setPicked}
          options={encounters.map((encounter) => ({
            value: String(encounter.id),
            label: encounterOptionLabel(encounter)
          }))}
          placeholder="Pick an encounter"
          searchPlaceholder="Search team, stage or round"
          triggerClassName="h-9"
        />
        <DialogFooter>
          <Button
            disabled={value === undefined || isPending}
            onClick={() => value !== undefined && onAttach(Number(value))}
          >
            {isPending ? <Spinner /> : <Link2 aria-hidden />}
            Attach and reprocess
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function TournamentLogsTab({
  tournamentId,
  workspaceId,
  encounters,
  canUploadLogs
}: Readonly<TournamentLogsTabProps>) {
  const format = useFormatter();
  const queryClient = useQueryClient();
  // Scoped to a tournament inside the hub, to the workspace on the
  // cross-tournament browser. Both keys are what realtime and the tab badge
  // address, so nothing here invents a key of its own.
  const historyKey = useMemo(
    () =>
      tournamentId != null
        ? getTournamentWorkspaceQueryKeys(tournamentId).logHistory
        : adminQueryKeys.workspaceLogHistory(workspaceId),
    [tournamentId, workspaceId]
  );

  const statsQuery = useQuery({
    queryKey: [...historyKey, "stats"],
    queryFn: () =>
      tournamentId != null
        ? adminService.getLogStats(tournamentId)
        : adminService.getLogStats(undefined, { workspaceId })
  });
  const stats = statsQuery.data;
  const queueActive = stats != null && stats.pending + stats.processing > 0;
  const isFetching = useIsFetching({ queryKey: historyKey }) > 0;

  // The table owns the page query, so the poll stales it from here. Only while
  // the queue has work: an idle console is driven by `workspace.logs` alone.
  useEffect(() => {
    if (!queueActive) return;
    const timer = setInterval(
      () => void queryClient.invalidateQueries({ queryKey: historyKey }),
      ACTIVE_QUEUE_POLL_MS
    );
    return () => clearInterval(timer);
  }, [queueActive, queryClient, historyKey]);

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
  const filters = useFilters(defs);
  const rawStatus = String(filters.values.status ?? "");
  const statusFilter = (LOG_FILTERS as readonly string[]).includes(rawStatus)
    ? (rawStatus as LogFilter)
    : null;

  const refreshAll = () => void queryClient.invalidateQueries({ queryKey: historyKey });

  // Parser completions arrive as `workspace.logs`, which stales exactly this
  // console's history key — and the stats query keyed under it. `tournamentId`
  // is what tells the registry which of the two variants of that key exists
  // here: the signal is workspace-wide, the console is mounted per tournament.
  useInvalidation({
    scopeKind: "workspace",
    scopeId: workspaceId,
    tournamentId
  });

  const retryMutation = useMutation({
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
        notify.success(queued === 1 ? "Log retry queued" : `Queued ${queued} logs for retry`);
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

  const [attachTarget, setAttachTarget] = useState<LogProcessingRecord | null>(null);
  const attachMutation = useMutation({
    mutationFn: ({ recordId, encounterId }: { recordId: number; encounterId: number }) =>
      adminService.retryLogRecord(recordId, encounterId),
    onSuccess: () => {
      notify.success("Log attached and queued");
      setAttachTarget(null);
      refreshAll();
    }
  });

  const columns: ColumnDef<LogProcessingRecord>[] = [
    {
      id: "file",
      header: "Log file",
      accessorFn: (record) => getLogFileName(record.filename),
      enableSorting: false,
      cell: ({ row }) => {
        const record = row.original;
        return (
          <p
            className="max-w-[22rem] truncate font-mono text-xs"
            title={`${record.filename}\n${SOURCE_LABELS[record.source]} by ${record.uploader_name ?? "unknown uploader"}${record.attempts > 1 ? `\n${record.attempts} processing attempts` : ""}`}
          >
            {getLogFileName(record.filename)}
          </p>
        );
      }
    },
    {
      id: "encounter",
      header: "Encounter",
      accessorFn: (record) => record.attached_encounter_name ?? "",
      enableSorting: false,
      cell: ({ row }) => (
        <p className="max-w-[16rem] truncate text-xs text-muted-foreground">
          {row.original.attached_encounter_name ?? "Not attached"}
        </p>
      )
    },
    {
      id: "status",
      header: "Status",
      accessorFn: (record) => STATUS_META[record.status].label,
      size: 136,
      enableSorting: false,
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5">
          <LogStatusBadge status={row.original.status} />
          {row.original.attempts > 1 ? (
            <span className="text-xs tabular-nums text-muted-foreground">
              ×{row.original.attempts}
            </span>
          ) : null}
        </div>
      )
    },
    {
      id: "error",
      header: "Error",
      accessorFn: (record) => record.error_message ?? "",
      enableSorting: false,
      cell: ({ row }) => {
        const errorSummary = getErrorSummary(row.original.error_message);
        if (!errorSummary) return null;
        return (
          <details className="group max-w-[28rem]">
            <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded text-xs text-danger focus-visible:outline-2 focus-visible:outline-offset-2">
              <ChevronRight
                className="size-3 shrink-0 transition-transform group-open:rotate-90"
                aria-hidden
              />
              {errorSummary}
            </summary>
            <pre
              tabIndex={0}
              className="mt-1.5 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/20 p-2 text-xs text-muted-foreground"
            >
              {row.original.error_message}
            </pre>
          </details>
        );
      }
    },
    {
      id: "created_at",
      header: "Uploaded",
      accessorFn: (record) => record.created_at,
      size: 128,
      enableSorting: false,
      meta: columnMeta<LogProcessingRecord>({ align: "right", numeric: true }),
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">
          {formatLogTime(format, row.original.created_at)}
        </span>
      )
    },
    {
      id: "duration",
      header: "Duration",
      accessorFn: (record) => formatDuration(record),
      size: 88,
      enableSorting: false,
      meta: columnMeta<LogProcessingRecord>({ align: "right", numeric: true }),
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">{formatDuration(row.original)}</span>
      )
    },
    // "Queued"/"Processing" rows go stale when the worker drops their queue
    // message; the reaper requeues them on its own schedule, this is the
    // operator's shortcut past the wait.
    createKebabColumn<LogProcessingRecord>(
      (record) => [
        {
          label: record.status === "failed" ? "Retry log" : "Requeue log",
          icon: RotateCcw,
          hidden: record.status === "done",
          onSelect: () => retryMutation.mutate([record.id])
        },
        // A processed log already filed its match; only an unfinished one can
        // be re-filed. The workspace-wide console holds no encounter list.
        {
          label: "Attach to encounter…",
          icon: Link2,
          hidden: record.status === "done" || encounters.length === 0,
          onSelect: () => setAttachTarget(record)
        }
      ],
      { rowLabel: (record) => getLogFileName(record.filename) }
    )
  ];

  return (
    <TooltipProvider>
      <div className="flex flex-col gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <FolderInput className="size-4 shrink-0 text-primary" aria-hidden />
            <h2 className="text-base font-semibold">Log processing</h2>
          </div>
          <p className="mt-1 text-pretty text-sm text-muted-foreground">
            Track uploaded and Discord/S3 match logs, isolate failures, and queue retries. Stalled
            logs are requeued automatically.
          </p>
        </div>

        {stats && stats.failed > 0 ? (
          <div className="flex flex-col gap-2 rounded-lg border border-danger/25 bg-danger/5 px-3 py-2 text-xs sm:flex-row sm:items-center sm:justify-between">
            <p className="min-w-0 text-danger">
              {stats.failed.toLocaleString()} log{stats.failed === 1 ? "" : "s"} failed to process
            </p>
            {statusFilter !== "failed" ? (
              <Button
                variant="outline"
                size="sm"
                className="h-7 shrink-0 text-xs"
                onClick={() => filters.set("status", "failed")}
              >
                Show failed
              </Button>
            ) : null}
          </div>
        ) : null}

        <DataTable<LogProcessingRecord>
          columns={columns}
          getRowId={(record) => String(record.id)}
          initialPageSize={PAGE_SIZE}
          filterKey={filters.filterKey}
          cellAlign="top"
          searchPlaceholder="Search file, error, uploader, encounter"
          emptyMessage={
            statusFilter != null
              ? "No logs in this status."
              : tournamentId != null
                ? "No logs for this tournament yet. Upload log files or process stored S3 logs."
                : "No logs in this workspace yet."
          }
          queryKey={(page, search, pageSize) => [
            ...historyKey,
            "list",
            statusFilter ?? "all",
            search.trim(),
            page,
            pageSize
          ]}
          queryFn={async (page, search, pageSize) => {
            const response = await adminService.getLogHistory(tournamentId ?? undefined, {
              limit: pageSize,
              offset: (page - 1) * pageSize,
              status: statusFilter ?? undefined,
              search: search.trim(),
              ...(tournamentId == null && { workspaceId })
            });
            return { results: response.items, total: response.total, page, per_page: pageSize };
          }}
          enableRowSelection={(row) => row.original.status !== "done"}
          bulkActions={(selected, clearSelection) => (
            <Button
              variant="outline"
              size="sm"
              className="h-8"
              disabled={retryMutation.isPending}
              onClick={() =>
                retryMutation.mutate(
                  selected.map((record) => record.id),
                  { onSuccess: clearSelection }
                )
              }
            >
              {retryMutation.isPending ? <Spinner /> : <RotateCcw aria-hidden />}
              Retry {selected.length}
            </Button>
          )}
          toolbar={
            <FilterBar
              defs={defs}
              filters={filters}
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
                          {formatLogTime(format, stats.last_created_at)}
                        </span>
                      </>
                    ) : null}
                  </p>
                ) : null
              }
            />
          }
          actions={
            <>
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
                  {processAllLogsMutation.isPending ? <Spinner /> : null}
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
                    disabled={isFetching}
                  >
                    <RefreshCw className={cn(isFetching && "animate-spin")} aria-hidden />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Refresh log processing</TooltipContent>
              </Tooltip>
            </>
          }
        />
      </div>
      <AttachLogDialog
        record={attachTarget}
        encounters={encounters}
        isPending={attachMutation.isPending}
        onAttach={(encounterId) =>
          attachTarget && attachMutation.mutate({ recordId: attachTarget.id, encounterId })
        }
        onClose={() => setAttachTarget(null)}
      />
    </TooltipProvider>
  );
}
