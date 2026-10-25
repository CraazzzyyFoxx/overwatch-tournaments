"use client";

import { useIsFetching, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { DataTable, type TableCommand } from "@/components/data-table";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { FilterBar } from "@/components/kit/FilterBar";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { useInvalidation } from "@/hooks/useInvalidation";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import { AttachLogDialog } from "./AttachLogDialog";
import {
  getLogFileName,
  getRetryKind,
  logOperationErrorCode,
  retryRequestFor
} from "./logs.helpers";
import { LOG_FILTERS, STATUS_META, formatLogTime, isRetryable, type LogFilter } from "./logs-tab/model";
import { useLogColumns } from "./logs-tab/useLogColumns";
import { getApiErrorMessage } from "@/lib/api/error";
import type { LogBindRequest, LogProcessingRecord } from "@/types/admin.types";
import type { Encounter } from "@/types/encounter.types";
import {
  TournamentLogUploadDialog,
  type TournamentLogUploadHandle
} from "@/components/logs/TournamentLogUploadDialog";
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

interface TournamentLogsTabProps {
  /** `null` = every tournament in the workspace. */
  tournamentId: number | null;
  workspaceId: number | null;
  encounters: Encounter[];
  canUploadLogs: boolean;
}

export function TournamentLogsTab({
  tournamentId,
  workspaceId,
  encounters,
  canUploadLogs
}: Readonly<TournamentLogsTabProps>) {
  const t = useTranslations("adminTournament.logs");
  const tx = useTranslations("adminTournament.logsExtra");
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
        label: t("status"),
        kind: "single",
        options: LOG_FILTERS.map((filter) => ({
          value: filter,
          label: t(STATUS_META[filter].key),
          // Counts come from the server aggregate, so a chip shows its real size.
          count: stats?.[filter]
        }))
      }
    ],
    [stats, t]
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

  const failureMessage = (reason: unknown) => {
    const code = logOperationErrorCode(reason);
    return code ? tx(`opError.${code}`) : getApiErrorMessage(reason);
  };

  const retryMutation = useMutation({
    // Each row is its own request: a done row reparses with the revision captured when the page was read, so
    // a stale, busy or superseded row fails alone and is reported by name.
    mutationFn: async (records: LogProcessingRecord[]) => {
      const results = await Promise.allSettled(
        records.map((record) => adminService.retryLogRecord(record.id, retryRequestFor(record)))
      );
      return results.flatMap((result, index) =>
        result.status === "rejected" ? [{ record: records[index]!, reason: result.reason }] : []
      );
    },
    onSuccess: (failures, records) => {
      const ok = records.length - failures.length;
      if (failures.length > 0) {
        notify.error(tx("retryPartial", { ok, total: records.length }), {
          description: (
            <ul className="list-disc pl-4">
              {failures.map(({ record, reason }) => (
                <li key={record.id}>{`${getLogFileName(record.filename)}: ${failureMessage(reason)}`}</li>
              ))}
            </ul>
          )
        });
      } else if (records.some((record) => getRetryKind(record) === "reparse")) {
        notify.success(tx("retryProcessed", { count: ok }));
      } else {
        notify.success(ok === 1 ? t("retryQueuedSingle") : t("retryQueuedPlural", { count: ok }));
      }
      refreshAll();
    }
  });

  const processAllLogsMutation = useMutation({
    mutationFn: () => adminService.processAllTournamentLogs(tournamentId!),
    onSuccess: () => {
      notify.success(t("processS3Queued"));
      refreshAll();
    }
  });

  const [attachTarget, setAttachTarget] = useState<LogProcessingRecord | null>(null);
  const attachMutation = useMutation({
    mutationFn: ({ recordId, encounterId, encounterGameId }: {
      recordId: number; encounterId: number; encounterGameId: number;
    }) => adminService.retryLogRecord(recordId, {
      encounter_id: encounterId,
      encounter_game_id: encounterGameId
    }),
    onSuccess: () => {
      notify.success(t("attachedQueued"));
      setAttachTarget(null);
      refreshAll();
    },
    onError: (error) => notify.apiError(error)
  });

  const bindMutation = useMutation({
    mutationFn: ({ recordId, request }: { recordId: number; request: LogBindRequest }) =>
      adminService.bindLogRecord(recordId, request),
    onSuccess: (job) => {
      if (job.status === "done") {
        notify.success(tx("bound"));
      } else {
        notify.error(tx("boundNotDone", { status: t(STATUS_META[job.status].key) }), { description: job.error?.message });
      }
      setAttachTarget(null);
      refreshAll();
    },
    onError: (error) => {
      const code = logOperationErrorCode(error);
      if (code == null) return notify.apiError(error);
      notify.error(tx(`opError.${code}`), { description: getApiErrorMessage(error) });
      // The operator's view is stale: re-read the list and the game's occupancy before another attempt.
      if (code === "stale_revision" || code === "expected_revision_required" || code === "stale_binding") {
        refreshAll();
      }
    }
  });

  const columns = useLogColumns({
    noEncounters: tournamentId != null && encounters.length === 0,
    onRetry: retryMutation.mutate,
    onAttach: setAttachTarget
  });

  const uploadRef = useRef<TournamentLogUploadHandle>(null);
  const commands: TableCommand[] = [
    {
      id: "upload",
      label: t("upload"),
      onSelect: () => uploadRef.current?.open(),
      hidden: !(canUploadLogs && tournamentId != null)
    },
    // Both endpoints are per tournament, so the workspace-wide console reads
    // without offering them.
    {
      id: "process-s3",
      label: t("processS3"),
      onSelect: () => processAllLogsMutation.mutate(),
      hidden: tournamentId == null,
      pending: processAllLogsMutation.isPending,
      disabled: processAllLogsMutation.isPending
    },
    {
      id: "refresh",
      label: t("refresh"),
      icon: RefreshCw,
      onSelect: refreshAll,
      pending: isFetching,
      disabled: isFetching
    }
  ];

  return (
    <>
      <div className="flex flex-col gap-3">
        {/* N failed -> Show failed (§15): the failures are the work on this tab. */}
        {stats && stats.failed > 0 && statusFilter !== "failed" ? (
          <Alert role="status">
            <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
              <span>{t("failedToProcess", { count: stats.failed })}</span>
              <Button
                variant="outline"
                size="sm"
                className="shrink-0"
                onClick={() => filters.set("status", "failed")}
              >
                {t("showFailed")}
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}
        <DataTable<LogProcessingRecord>
          columns={columns}
          getRowId={(record) => String(record.id)}
          initialPageSize={PAGE_SIZE}
          filterKey={filters.filterKey}
          cellAlign="top"
          searchPlaceholder={t("search")}
          emptyMessage={
            statusFilter != null
              ? tx("noStatusLogs")
              : tournamentId != null
                ? tx("noTournamentLogs")
                : tx("noWorkspaceLogs")
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
          enableRowSelection={(row) => isRetryable(row.original)}
          bulkActions={(selected, clearSelection) => (
            <Button
              variant="outline"
              size="sm"
              disabled={retryMutation.isPending || !selected.some(isRetryable)}
              onClick={() => {
                const retryable = selected.filter(isRetryable);
                if (retryable.length > 0) {
                  retryMutation.mutate(retryable, { onSuccess: clearSelection });
                }
              }}
            >
              {retryMutation.isPending ? <Spinner /> : null}
              {tx("retrySelected", { count: selected.length })}
            </Button>
          )}
          toolbar={<FilterBar defs={defs} filters={filters} />}
          summary={
            stats
              ? stats.last_created_at
                ? tx("summaryNewest", {
                    count: stats.total,
                    average: stats.avg_duration_seconds?.toFixed(1) ?? "none",
                    time: formatLogTime(format, stats.last_created_at)
                  })
                : tx("summary", {
                    count: stats.total,
                    average: stats.avg_duration_seconds?.toFixed(1) ?? "none"
                  })
              : null
          }
          commands={commands}
        />
      </div>
      {canUploadLogs && tournamentId != null ? (
        <TournamentLogUploadDialog
          ref={uploadRef}
          tournamentId={tournamentId}
          encounters={encounters}
          onUploaded={() => {
            invalidateTournamentWorkspace(queryClient, tournamentId);
            refreshAll();
          }}
        />
      ) : null}
      {attachTarget ? (
        <AttachLogDialog
          key={attachTarget.id}
          record={attachTarget}
          encounters={encounters.filter((encounter) =>
            attachTarget.tournament_id == null || encounter.tournament_id === attachTarget.tournament_id
          )}
          pickTournament={tournamentId == null}
          historyKey={historyKey}
          workspaceId={workspaceId}
          isPending={attachMutation.isPending || bindMutation.isPending}
          onAttach={(encounterId, encounterGameId) =>
            attachMutation.mutate({ recordId: attachTarget.id, encounterId, encounterGameId })
          }
          onBind={(request) => bindMutation.mutate({ recordId: attachTarget.id, request })}
          onClose={() => setAttachTarget(null)}
        />
      ) : null}
    </>
  );
}
