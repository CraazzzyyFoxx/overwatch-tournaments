"use client";

import { History, Wifi, WifiOff } from "lucide-react";

import { CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { SurfaceCard } from "./SurfaceCard";
import type { LogStreamState } from "@/hooks/useLogStream";

interface LogProcessingQueueProps {
  logStream: LogStreamState;
}

export function LogProcessingQueue({ logStream }: LogProcessingQueueProps) {
  return (
    <SurfaceCard>
      <CardHeader className="p-5 pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <History className="size-4 text-muted-foreground" />
              Log Queue
            </CardTitle>
            <CardDescription className="mt-1 text-xs">Real-time queue depths</CardDescription>
          </div>
          <div className="flex items-center gap-1.5 text-xs">
            {logStream.connected ? (
              <>
                <Wifi className="size-3.5 text-green-500" />
                <span className="text-muted-foreground">Live</span>
              </>
            ) : (
              <>
                <WifiOff className="size-3.5 text-muted-foreground" />
                <span className="text-muted-foreground">{logStream.error ?? "Connecting..."}</span>
              </>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 px-5 pb-5">
        {/* Queue depths — 2-col grid since it's in the left column */}
        {logStream.queues.length > 0 ? (
          <div className="grid gap-2 grid-cols-2">
            {logStream.queues.map((q) => {
              const isOffline = q.status === "not_found";
              const isError = q.status === "error";
              const isUnavailable = isOffline || isError;

              return (
                <div
                  key={q.name}
                  className={`rounded-xl border p-3 space-y-2 ${
                    isUnavailable
                      ? "border-border/30 bg-background/25 opacity-60"
                      : "border-border/50 bg-background/45"
                  }`}
                >
                  <p className="text-xs font-medium text-muted-foreground truncate">
                    {q.name.replace(/_/g, " ")}
                  </p>
                  <div className="flex items-end justify-between">
                    {isUnavailable ? (
                      <span className={`text-xs font-medium ${isError ? "text-destructive" : "text-muted-foreground"}`}>
                        {isError ? "Error" : "Offline"}
                      </span>
                    ) : (
                      <span className="text-xl font-semibold tabular-nums">{q.messages_ready}</span>
                    )}
                    {q.messages_unacknowledged > 0 && (
                      <span className="text-xs text-amber-500">+{q.messages_unacknowledged} processing</span>
                    )}
                  </div>
                  {!isUnavailable && (
                    <Progress value={Math.min(100, q.messages_ready * 10)} className="h-1" />
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">
            {logStream.connected ? "No queue data yet..." : "Waiting for connection..."}
          </div>
        )}

        {/* Recent log records — limited to 6 */}
        {logStream.recentLogs.length > 0 && (
          <div className="space-y-1">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Recent activity
            </p>
            <div className="divide-y divide-border/50 rounded-xl border border-border/50 overflow-hidden">
              {logStream.recentLogs.slice(0, 6).map((record) => {
                const statusColors: Record<string, string> = {
                  pending: "text-muted-foreground",
                  processing: "text-blue-500",
                  done: "text-green-600",
                  failed: "text-destructive",
                };
                return (
                  <div
                    key={record.id}
                    className="flex items-center justify-between gap-3 px-3 py-2 bg-background/40 text-sm"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className={`shrink-0 text-xs font-medium uppercase ${statusColors[record.status] ?? ""}`}>
                        {record.status}
                      </span>
                      <span className="truncate font-mono text-xs text-muted-foreground">
                        {record.filename.split("/").at(-1)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0 text-xs text-muted-foreground">
                      {record.uploader_name && <span>{record.uploader_name}</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {logStream.lastUpdated && (
          <p className="text-right text-xs text-muted-foreground/60">
            Updated {logStream.lastUpdated.toLocaleTimeString()}
          </p>
        )}
      </CardContent>
    </SurfaceCard>
  );
}
