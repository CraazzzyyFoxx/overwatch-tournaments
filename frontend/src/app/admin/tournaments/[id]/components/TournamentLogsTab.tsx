"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Eye,
  FileText,
  FolderInput,
  Loader2,
  RefreshCw,
  RotateCcw,
  Search,
  Upload,
  XCircle
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Fragment, useState } from "react";
import {
  AdminDetailTableShell,
  getAdminDetailTableStyles
} from "@/components/admin/AdminDetailTable";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { LogProcessingRecord, LogProcessingStatus } from "@/types/admin.types";
import type { Encounter } from "@/types/encounter.types";
import { TournamentLogUploadDialog } from "./TournamentLogUploadDialog";
import {
  getTournamentWorkspaceQueryKeys,
  invalidateTournamentWorkspace
} from "./tournamentWorkspace.queryKeys";

const PAGE_SIZE = 20;

type LogFilter = LogProcessingStatus | "all";

const LOG_FILTERS: Array<{ value: LogFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "failed", label: "Failed" },
  { value: "done", label: "Processed" },
  { value: "processing", label: "Processing" },
  { value: "pending", label: "Queued" }
];

const STATUS_META: Record<
  LogProcessingStatus,
  { label: string; icon: LucideIcon; className: string }
> = {
  pending: {
    label: "Queued",
    icon: Clock3,
    className: "border-muted-foreground/20 bg-muted/20 text-muted-foreground"
  },
  processing: {
    label: "Processing",
    icon: Loader2,
    className: "border-blue-400/25 bg-blue-400/10 text-blue-300"
  },
  done: {
    label: "Processed",
    icon: CheckCircle2,
    className: "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
  },
  failed: {
    label: "Failed",
    icon: XCircle,
    className: "border-destructive/35 bg-destructive/10 text-destructive"
  }
};

const SOURCE_LABELS: Record<LogProcessingRecord["source"], string> = {
  upload: "Upload",
  discord: "Discord",
  manual: "Manual"
};

interface TournamentLogsTabProps {
  tournamentId: number;
  encounters: Encounter[];
  canUploadLogs: boolean;
  enabled: boolean;
}

function getLogFileName(filename: string) {
  return filename.split(/[\\/]/).at(-1) ?? filename;
}

function getDurationSeconds(record: LogProcessingRecord) {
  if (!record.started_at || !record.finished_at) return null;

  const durationMs = new Date(record.finished_at).getTime() - new Date(record.started_at).getTime();
  return Number.isFinite(durationMs) && durationMs >= 0 ? durationMs / 1000 : null;
}

function formatDuration(record: LogProcessingRecord) {
  const duration = getDurationSeconds(record);

  if (duration != null) {
    return `${duration.toFixed(1)}s`;
  }

  return record.status === "processing" ? "In progress" : "-";
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString();
}

function getErrorSummary(errorMessage: string | null) {
  if (!errorMessage) return null;

  const codeMatch = errorMessage.match(/['"]code['"]:\s*['"]([^'"]+)['"]/);
  const statusMatch = errorMessage.match(/^(\d{3})/);
  const code = codeMatch?.[1]?.replaceAll("_", " ");

  if (code) {
    const formattedCode = code.charAt(0).toUpperCase() + code.slice(1);
    return statusMatch ? `${statusMatch[1]} - ${formattedCode}` : formattedCode;
  }

  return errorMessage.replace(/^(\d{3}:\s*)?/, "").slice(0, 120);
}

function matchesLogSearch(record: LogProcessingRecord, searchTerm: string) {
  if (!searchTerm) return true;

  const haystack = [
    record.filename,
    getLogFileName(record.filename),
    record.status,
    record.source,
    record.uploader_name,
    record.attached_encounter_name,
    record.error_message
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  return haystack.includes(searchTerm);
}

function LogStatusBadge({ status }: { status: LogProcessingStatus }) {
  const meta = STATUS_META[status];
  const Icon = meta.icon;

  return (
    <Badge variant="outline" className={cn("gap-1.5 whitespace-nowrap", meta.className)}>
      <Icon className={cn("size-3", status === "processing" && "animate-spin")} />
      {meta.label}
    </Badge>
  );
}

function MetricCell({
  label,
  value,
  detail,
  tone = "default"
}: {
  label: string;
  value: string;
  detail: string;
  tone?: "default" | "success" | "warning" | "danger";
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border/45 bg-background/55 px-3 py-2",
        tone === "success" && "border-emerald-500/20 bg-emerald-500/5",
        tone === "warning" && "border-amber-500/20 bg-amber-500/5",
        tone === "danger" && "border-destructive/25 bg-destructive/5"
      )}
    >
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 text-lg font-semibold tabular-nums">{value}</p>
      <p className="mt-0.5 text-[12px] text-muted-foreground">{detail}</p>
    </div>
  );
}

export function TournamentLogsTab({
  tournamentId,
  encounters,
  canUploadLogs,
  enabled
}: TournamentLogsTabProps) {
  const queryClient = useQueryClient();
  const tableStyles = getAdminDetailTableStyles("compact");
  const queryKeys = getTournamentWorkspaceQueryKeys(tournamentId);
  const [page, setPage] = useState(0);
  const [statusFilter, setStatusFilter] = useState<LogFilter>("all");
  const [searchTerm, setSearchTerm] = useState("");
  const [expandedRecordId, setExpandedRecordId] = useState<number | null>(null);

  const logHistoryQuery = useQuery({
    queryKey: [...queryKeys.logHistory, page],
    queryFn: () =>
      adminService.getLogHistory(tournamentId, { limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
    enabled,
    refetchInterval: enabled ? 10_000 : false,
    placeholderData: (prev) => prev
  });

  const retryLogMutation = useMutation({
    mutationFn: (recordId: number) => adminService.retryLogRecord(recordId),
    onSuccess: () => {
      notify.success("Log retry queued");
      logHistoryQuery.refetch();
    }
  });

  const retryVisibleFailedMutation = useMutation({
    mutationFn: (recordIds: number[]) =>
      Promise.all(recordIds.map((recordId) => adminService.retryLogRecord(recordId))),
    onSuccess: (_records, recordIds) => {
      notify.success("Failed logs queued", {
        description: `${recordIds.length} visible failed log${recordIds.length === 1 ? "" : "s"} sent for retry.`
      });
      logHistoryQuery.refetch();
    }
  });

  const processAllLogsMutation = useMutation({
    mutationFn: () => adminService.processAllTournamentLogs(tournamentId),
    onSuccess: () => {
      notify.success("Processing queued for all S3 logs");
      logHistoryQuery.refetch();
    }
  });

  const logRecords = logHistoryQuery.data?.items ?? [];
  const totalLogs = logHistoryQuery.data?.total ?? 0;
  const failedLogs = logRecords.filter((record) => record.status === "failed").length;
  const processingLogs = logRecords.filter((record) => record.status === "processing").length;
  const doneLogs = logRecords.filter((record) => record.status === "done").length;
  const pendingLogs = logRecords.filter((record) => record.status === "pending").length;
  const visibleFailedRecords = logRecords.filter((record) => record.status === "failed");
  const normalizedSearchTerm = searchTerm.trim().toLowerCase();
  const filteredRecords = logRecords.filter(
    (record) =>
      (statusFilter === "all" || record.status === statusFilter) &&
      matchesLogSearch(record, normalizedSearchTerm)
  );
  const completedDurations = logRecords
    .map(getDurationSeconds)
    .filter((duration): duration is number => duration != null);
  const averageDuration =
    completedDurations.length > 0
      ? `${(
          completedDurations.reduce((total, duration) => total + duration, 0) /
          completedDurations.length
        ).toFixed(1)}s`
      : "-";
  const lastUploadLabel = logRecords[0] ? formatDateTime(logRecords[0].created_at) : "-";
  const rangeStart = totalLogs === 0 ? 0 : page * PAGE_SIZE + 1;
  const rangeEnd = Math.min((page + 1) * PAGE_SIZE, totalLogs);
  const totalPages = Math.max(1, Math.ceil(totalLogs / PAGE_SIZE));
  const hasActiveFilter = statusFilter !== "all" || normalizedSearchTerm.length > 0;

  const renderRecordActions = (record: LogProcessingRecord, showPlaceholder = false) => {
    const isRetryingThisRecord =
      (retryLogMutation.isPending && retryLogMutation.variables === record.id) ||
      (retryVisibleFailedMutation.isPending &&
        retryVisibleFailedMutation.variables?.includes(record.id));

    if (record.status !== "failed" && showPlaceholder) {
      return <span className="text-xs text-muted-foreground">-</span>;
    }

    if (record.status !== "failed") {
      return null;
    }

    return (
      <div className="flex items-center justify-end gap-1">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="size-8"
              aria-label={`Retry processing ${getLogFileName(record.filename)}`}
              disabled={isRetryingThisRecord}
              onClick={() => retryLogMutation.mutate(record.id)}
            >
              {isRetryingThisRecord ? <Loader2 className="animate-spin" /> : <RotateCcw />}
            </Button>
          </TooltipTrigger>
          <TooltipContent>Retry log</TooltipContent>
        </Tooltip>
        <Button
          variant="ghost"
          size="sm"
          className="h-8"
          aria-expanded={expandedRecordId === record.id}
          onClick={() =>
            setExpandedRecordId((current) => (current === record.id ? null : record.id))
          }
        >
          <Eye />
          Details
        </Button>
      </div>
    );
  };

  return (
    <TooltipProvider>
      <Card className="border-border/40">
        <CardHeader className="gap-3 pb-3">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <FolderInput className="size-4 shrink-0 text-primary" />
                <CardTitle className="text-base font-semibold">Log Processing Console</CardTitle>
                <Badge variant={failedLogs > 0 ? "destructive" : "outline"}>
                  {failedLogs} failed on page
                </Badge>
              </div>
              <CardDescription className="mt-1">
                Monitor uploaded and Discord/S3-sourced match logs, isolate failures, and queue
                retries without scanning every row.
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-1">
              {canUploadLogs ? (
                <TournamentLogUploadDialog
                  tournamentId={tournamentId}
                  encounters={encounters}
                  onUploaded={() => {
                    invalidateTournamentWorkspace(queryClient, tournamentId);
                    logHistoryQuery.refetch();
                  }}
                  trigger={
                    <Button variant="outline" size="sm">
                      <Upload />
                      Upload Logs
                    </Button>
                  }
                />
              ) : null}
              <Button
                variant="outline"
                size="sm"
                disabled={processAllLogsMutation.isPending}
                onClick={() => processAllLogsMutation.mutate()}
              >
                {processAllLogsMutation.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <FolderInput />
                )}
                Process S3
              </Button>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-8"
                    aria-label="Refresh log history"
                    onClick={() => logHistoryQuery.refetch()}
                    disabled={logHistoryQuery.isFetching}
                  >
                    <RefreshCw className={cn(logHistoryQuery.isFetching && "animate-spin")} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Refresh logs</TooltipContent>
              </Tooltip>
            </div>
          </div>
        </CardHeader>

        <CardContent className="flex flex-col gap-4 p-4 pt-0">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
            <MetricCell label="Total" value={totalLogs.toLocaleString()} detail="all records" />
            <MetricCell
              label="Processed"
              value={doneLogs.toLocaleString()}
              detail="on this page"
              tone="success"
            />
            <MetricCell
              label="Failed"
              value={failedLogs.toLocaleString()}
              detail="on this page"
              tone={failedLogs > 0 ? "danger" : "default"}
            />
            <MetricCell
              label="Queue"
              value={(pendingLogs + processingLogs).toLocaleString()}
              detail={`${pendingLogs} queued, ${processingLogs} running`}
              tone={processingLogs > 0 ? "warning" : "default"}
            />
            <MetricCell label="Avg time" value={averageDuration} detail="page completed" />
          </div>

          <div className="flex flex-col gap-1 rounded-lg border border-border/40 bg-muted/10 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Last upload
              </p>
              <p className="mt-0.5 text-sm font-medium">{lastUploadLabel}</p>
            </div>
            <p className="text-xs text-muted-foreground">
              Showing {rangeStart}-{rangeEnd} of {totalLogs.toLocaleString()} records
            </p>
          </div>

          {failedLogs > 0 ? (
            <Alert className="border-destructive/30 bg-destructive/5">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>
                {failedLogs} log{failedLogs === 1 ? "" : "s"} on this page need attention
              </AlertTitle>
              <AlertDescription className="flex flex-col gap-3 pt-1 sm:flex-row sm:items-center sm:justify-between">
                <span>
                  {getErrorSummary(visibleFailedRecords[0]?.error_message) ??
                    "Review failed records and retry after fixing the match state."}
                </span>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setStatusFilter("failed");
                      setExpandedRecordId(visibleFailedRecords[0]?.id ?? null);
                    }}
                  >
                    <Eye />
                    View failed
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={retryVisibleFailedMutation.isPending}
                    onClick={() =>
                      retryVisibleFailedMutation.mutate(
                        visibleFailedRecords.map((record) => record.id)
                      )
                    }
                  >
                    {retryVisibleFailedMutation.isPending ? (
                      <Loader2 className="animate-spin" />
                    ) : (
                      <RotateCcw />
                    )}
                    Retry visible failed
                  </Button>
                </div>
              </AlertDescription>
            </Alert>
          ) : null}

          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <ToggleGroup
              type="single"
              value={statusFilter}
              onValueChange={(value) => {
                setStatusFilter(value as LogFilter);
                setExpandedRecordId(null);
              }}
              className="w-full flex-wrap justify-start lg:w-auto"
              size="sm"
              variant="outline"
            >
              {LOG_FILTERS.map((filter) => (
                <ToggleGroupItem key={filter.value} value={filter.value} className="text-xs">
                  {filter.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <div className="relative w-full lg:max-w-sm">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder="Search visible logs..."
                className="h-8 pl-8 text-xs"
                aria-label="Search visible log records"
              />
            </div>
          </div>

          {logHistoryQuery.isLoading ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : !logHistoryQuery.data?.items.length ? (
            <div className="rounded-lg border border-dashed border-border/50 px-4 py-8 text-center">
              <FileText className="mx-auto size-7 text-muted-foreground" />
              <p className="mt-3 text-sm font-medium">No log processing records yet</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Upload logs or process S3 logs to populate this console.
              </p>
            </div>
          ) : filteredRecords.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border/50 px-4 py-8 text-center">
              <Search className="mx-auto size-7 text-muted-foreground" />
              <p className="mt-3 text-sm font-medium">No records match these filters</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Clear search or switch back to All to see the visible page.
              </p>
              {hasActiveFilter ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-4"
                  onClick={() => {
                    setStatusFilter("all");
                    setSearchTerm("");
                    setExpandedRecordId(null);
                  }}
                >
                  Clear filters
                </Button>
              ) : null}
            </div>
          ) : (
            <>
              <AdminDetailTableShell variant="compact" className="hidden lg:block">
                <Table className="table-fixed">
                  <TableHeader>
                    <TableRow className={tableStyles.headerRow}>
                      <TableHead className={cn(tableStyles.head, "w-[30%]")}>Log file</TableHead>
                      <TableHead className={cn(tableStyles.head, "w-[13%]")}>Result</TableHead>
                      <TableHead className={cn(tableStyles.head, "w-[12%]")}>Source</TableHead>
                      <TableHead className={cn(tableStyles.head, "w-[18%]")}>Uploaded</TableHead>
                      <TableHead className={cn(tableStyles.head, "w-[10%]")}>Duration</TableHead>
                      <TableHead className={cn(tableStyles.head, "w-[17%] text-right")}>
                        Actions
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredRecords.map((record) => {
                      const isExpanded = expandedRecordId === record.id;
                      const errorSummary = getErrorSummary(record.error_message);

                      return (
                        <Fragment key={record.id}>
                          <TableRow
                            className={cn(
                              tableStyles.row,
                              record.status === "failed" &&
                                "bg-destructive/5 hover:bg-destructive/10"
                            )}
                          >
                            <TableCell className={tableStyles.cell}>
                              <div className="flex min-w-0 flex-col gap-1">
                                <span className="truncate font-mono text-xs">
                                  {getLogFileName(record.filename)}
                                </span>
                                <span className="truncate text-xs text-muted-foreground">
                                  {record.attached_encounter_name ?? "Not attached"} -{" "}
                                  {record.uploader_name ?? "Unknown uploader"}
                                </span>
                                {errorSummary ? (
                                  <span className="truncate text-xs text-destructive">
                                    {errorSummary}
                                  </span>
                                ) : null}
                              </div>
                            </TableCell>
                            <TableCell className={tableStyles.cell}>
                              <LogStatusBadge status={record.status} />
                            </TableCell>
                            <TableCell className={tableStyles.cell}>
                              <Badge variant="outline" className="capitalize">
                                {SOURCE_LABELS[record.source]}
                              </Badge>
                            </TableCell>
                            <TableCell className={tableStyles.cell}>
                              <span className="text-sm">{formatDateTime(record.created_at)}</span>
                            </TableCell>
                            <TableCell className={tableStyles.cell}>
                              <span className="text-sm text-muted-foreground">
                                {formatDuration(record)}
                              </span>
                            </TableCell>
                            <TableCell className={cn(tableStyles.cell, "text-right")}>
                              {renderRecordActions(record, true)}
                            </TableCell>
                          </TableRow>
                          {isExpanded ? (
                            <TableRow className="bg-muted/10">
                              <TableCell colSpan={6} className="px-3 py-3">
                                <div className="grid gap-3 rounded-lg border border-border/40 bg-background/70 p-3 md:grid-cols-[180px_1fr]">
                                  <div>
                                    <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                                      Error detail
                                    </p>
                                    <p className="mt-1 text-sm font-medium">
                                      {errorSummary ?? "No error details"}
                                    </p>
                                  </div>
                                  <pre className="max-h-28 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/20 p-3 text-xs text-muted-foreground">
                                    {record.error_message ?? "No raw response available."}
                                  </pre>
                                </div>
                              </TableCell>
                            </TableRow>
                          ) : null}
                        </Fragment>
                      );
                    })}
                  </TableBody>
                </Table>
              </AdminDetailTableShell>

              <div className="flex flex-col gap-2 lg:hidden">
                {filteredRecords.map((record) => {
                  const errorSummary = getErrorSummary(record.error_message);
                  const isExpanded = expandedRecordId === record.id;

                  return (
                    <div
                      key={record.id}
                      className={cn(
                        "rounded-lg border border-border/45 bg-background/60 p-3",
                        record.status === "failed" && "border-destructive/25 bg-destructive/5"
                      )}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate font-mono text-xs">
                            {getLogFileName(record.filename)}
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {formatDateTime(record.created_at)} - {formatDuration(record)}
                          </p>
                        </div>
                        <LogStatusBadge status={record.status} />
                      </div>
                      <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                        <div>
                          <span className="text-muted-foreground">Encounter</span>
                          <p className="mt-0.5 font-medium">
                            {record.attached_encounter_name ?? "Not attached"}
                          </p>
                        </div>
                        <div>
                          <span className="text-muted-foreground">Source</span>
                          <p className="mt-0.5 font-medium">{SOURCE_LABELS[record.source]}</p>
                        </div>
                        <div>
                          <span className="text-muted-foreground">Uploader</span>
                          <p className="mt-0.5 font-medium">
                            {record.uploader_name ?? "Unknown uploader"}
                          </p>
                        </div>
                      </div>
                      {errorSummary ? (
                        <p className="mt-3 rounded-md bg-destructive/10 px-2 py-1.5 text-xs text-destructive">
                          {errorSummary}
                        </p>
                      ) : null}
                      {record.status === "failed" ? (
                        <div className="mt-3 flex justify-end">{renderRecordActions(record)}</div>
                      ) : null}
                      {isExpanded ? (
                        <pre className="mt-3 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border/40 bg-muted/15 p-3 text-xs text-muted-foreground">
                          {record.error_message ?? "No raw response available."}
                        </pre>
                      ) : null}
                    </div>
                  );
                })}
              </div>

              {totalLogs > PAGE_SIZE ? (
                <div className="flex flex-col gap-2 rounded-lg border border-border/40 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
                  <span className="text-[12px] text-muted-foreground">
                    Showing {rangeStart}-{rangeEnd} of {totalLogs.toLocaleString()} logs
                  </span>
                  <div className="flex items-center justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-8"
                      aria-label="Previous log page"
                      disabled={page === 0 || logHistoryQuery.isFetching}
                      onClick={() => {
                        setExpandedRecordId(null);
                        setPage((p) => p - 1);
                      }}
                    >
                      <ChevronLeft />
                    </Button>
                    <span className="min-w-16 text-center text-[12px] text-muted-foreground">
                      {page + 1} / {totalPages}
                    </span>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-8"
                      aria-label="Next log page"
                      disabled={(page + 1) * PAGE_SIZE >= totalLogs || logHistoryQuery.isFetching}
                      onClick={() => {
                        setExpandedRecordId(null);
                        setPage((p) => p + 1);
                      }}
                    >
                      <ChevronRight />
                    </Button>
                  </div>
                </div>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>
    </TooltipProvider>
  );
}
