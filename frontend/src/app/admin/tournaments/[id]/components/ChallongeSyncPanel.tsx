"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  CheckCircle2,
  ExternalLink,
  Loader2,
  XCircle
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { ChallongeSyncLogEntry } from "@/types/admin.types";
import { invalidateTournamentWorkspace } from "./tournamentWorkspace.queryKeys";

interface ChallongeSyncPanelProps {
  tournamentId: number;
  hasChallongeSource: boolean;
}

function formatSyncTime(value: string) {
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function getLogTone(status: ChallongeSyncLogEntry["status"]) {
  if (status === "success") return "border-emerald-700/60 bg-emerald-950/20 text-emerald-300";
  if (status === "conflict") return "border-amber-700/60 bg-amber-950/20 text-amber-200";
  return "border-destructive/50 bg-destructive/10 text-destructive";
}

export function ChallongeSyncPanel({ tournamentId, hasChallongeSource }: ChallongeSyncPanelProps) {
  const queryClient = useQueryClient();

  const { data: logs = [], isLoading } = useQuery({
    queryKey: ["admin", "challonge-sync-log", tournamentId],
    queryFn: () => adminService.challongeSyncLog(tournamentId, 20),
    enabled: hasChallongeSource
  });

  const invalidateSyncLog = () => {
    void queryClient.invalidateQueries({
      queryKey: ["admin", "challonge-sync-log", tournamentId]
    });
  };

  const importMutation = useMutation({
    mutationFn: () => adminService.challongeImport(tournamentId),
    onSuccess: () => {
      invalidateSyncLog();
      void queryClient.invalidateQueries({
        queryKey: ["admin", "tournament", tournamentId]
      });
      invalidateTournamentWorkspace(queryClient, tournamentId);
      notify.success("Challonge import started", { description: "Sync log will update shortly." });
    }
  });

  const exportMutation = useMutation({
    mutationFn: () => adminService.challongeExport(tournamentId),
    onSuccess: () => {
      invalidateSyncLog();
      notify.success("Challonge export started", { description: "Sync log will update shortly." });
    }
  });

  const lastLog = logs[0];
  const failedLogCount = logs.filter((log) => log.status !== "success").length;

  return (
    <Card className="border-border/40">
      <CardHeader className="gap-3 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              {hasChallongeSource ? (
                <CheckCircle2 className="size-4 text-primary" />
              ) : (
                <XCircle className="size-4 text-muted-foreground" />
              )}
              <CardTitle className="text-sm font-semibold">Challonge Sync</CardTitle>
            </div>
            <CardDescription className="mt-1 text-xs">
              {hasChallongeSource
                ? "Import and export bracket state from the linked Challonge source."
                : "Link a tournament or stage to enable external bracket sync."}
            </CardDescription>
          </div>
          <Badge
            variant="outline"
            className={cn(
              "shrink-0",
              hasChallongeSource
                ? "border-primary/40 bg-primary/10 text-primary"
                : "border-border/70 text-muted-foreground"
            )}
          >
            {hasChallongeSource ? "Connected" : "Not linked"}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        <div className="grid gap-2 sm:grid-cols-2">
          <Button
            size="sm"
            disabled={!hasChallongeSource || importMutation.isPending}
            onClick={() => importMutation.mutate()}
          >
            {importMutation.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <ArrowDownToLine className="size-4" />
            )}
            {importMutation.isPending ? "Importing..." : "Import"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={!hasChallongeSource || exportMutation.isPending}
            onClick={() => exportMutation.mutate()}
          >
            {exportMutation.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <ArrowUpFromLine className="size-4" />
            )}
            {exportMutation.isPending ? "Exporting..." : "Export"}
          </Button>
        </div>

        {hasChallongeSource ? (
          <div className="rounded-lg border border-border/60 bg-muted/10 p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  Last Sync
                </p>
                {isLoading ? (
                  <p className="mt-1 text-sm text-muted-foreground">Loading sync state...</p>
                ) : lastLog ? (
                  <p className="mt-1 text-sm">
                    {lastLog.direction} {lastLog.entity_type}
                    {lastLog.entity_id ? ` #${lastLog.entity_id}` : ""}
                  </p>
                ) : (
                  <p className="mt-1 text-sm text-muted-foreground">No sync history yet</p>
                )}
              </div>
              {lastLog ? (
                <div className="text-right">
                  <Badge variant="outline" className={cn("mb-1", getLogTone(lastLog.status))}>
                    {lastLog.status}
                  </Badge>
                  <p className="text-xs text-muted-foreground">
                    {formatSyncTime(lastLog.created_at)}
                  </p>
                </div>
              ) : null}
            </div>
            {failedLogCount > 0 ? (
              <p className="mt-3 text-xs text-amber-200">
                {failedLogCount} recent sync event{failedLogCount === 1 ? "" : "s"} need review.
              </p>
            ) : null}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-border/70 bg-muted/10 p-3 text-sm text-muted-foreground">
            Add a Challonge URL or stage slug in tournament settings before running sync actions.
          </div>
        )}

        {hasChallongeSource ? (
          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Sync Log
              </p>
              <Badge variant="outline">{logs.length} recent</Badge>
            </div>

            {isLoading ? (
              <div className="text-sm text-muted-foreground">Loading...</div>
            ) : logs.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border/70 px-3 py-2 text-sm text-muted-foreground">
                No sync history
              </div>
            ) : (
              <div className="max-h-[260px] overflow-y-auto rounded-lg border border-border/60">
                {logs.map((log) => (
                  <div
                    key={log.id}
                    className="flex items-center gap-2 border-b border-border/50 px-3 py-2 text-xs last:border-b-0"
                  >
                    <Badge variant="outline" className="w-14 justify-center text-[10px] capitalize">
                      {log.direction}
                    </Badge>
                    <Badge
                      variant="outline"
                      className={cn("w-16 justify-center text-[10px]", getLogTone(log.status))}
                    >
                      {log.status}
                    </Badge>
                    <span className="min-w-0 flex-1 truncate text-muted-foreground">
                      {log.entity_type}
                      {log.entity_id ? ` #${log.entity_id}` : ""}
                      {log.error_message ? ` - ${log.error_message}` : ""}
                    </span>
                    {log.challonge_id ? (
                      <span className="hidden items-center gap-1 text-muted-foreground lg:inline-flex">
                        <ExternalLink className="size-3" />
                        {log.challonge_id}
                      </span>
                    ) : null}
                    <span className="shrink-0 text-muted-foreground">
                      {formatSyncTime(log.created_at)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
