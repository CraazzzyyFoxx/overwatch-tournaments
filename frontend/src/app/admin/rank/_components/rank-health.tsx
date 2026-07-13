"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2, Pause, Play, RotateCcw, Settings } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { RankCollectionStats } from "@/types/admin.types";

import { STATUS_BAR, STATUS_ORDER, formatRelative } from "./rank-shared";

const RANK_KEY = "parser.rank_collection";

function pct(n: number, total: number): string {
  return total ? `${Math.round((n / total) * 100)}%` : "0%";
}

function formatInterval(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600}h`;
  if (seconds % 60 === 0) return `${seconds / 60}m`;
  return `${seconds}s`;
}

function StatusBar({ stats }: { stats: RankCollectionStats }) {
  const total = stats.total || 1;
  const counts = stats.by_status;
  return (
    <div className="space-y-2">
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-white/5">
        {STATUS_ORDER.map((s) =>
          counts[s] ? (
            <div
              key={s}
              className={cn("h-full", STATUS_BAR[s])}
              style={{ width: `${(counts[s] / total) * 100}%` }}
              title={`${s}: ${counts[s]}`}
            />
          ) : null
        )}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
        {STATUS_ORDER.map((s) =>
          counts[s] ? (
            <span key={s} className="inline-flex items-center gap-1.5 text-muted-foreground">
              <span className={cn("h-2 w-2 rounded-full", STATUS_BAR[s])} />
              {s} <span className="tabular-nums text-foreground">{counts[s]}</span>
            </span>
          ) : null
        )}
      </div>
    </div>
  );
}

export function RankHealthDashboard() {
  const queryClient = useQueryClient();
  const { user } = useAuthProfile();
  const isSuperuser = user?.isSuperuser ?? false;

  const statsQuery = useQuery({
    queryKey: ["admin", "rank", "stats"],
    queryFn: () => adminService.getRankCollectionStats(),
    refetchInterval: 10000
  });
  const stats = statsQuery.data;

  const reenableMutation = useMutation({
    mutationFn: () => adminService.reenableDisabledRankCollection(false),
    onSuccess: (result) => {
      notify.success(`Re-enabled ${result.reenabled} disabled battle tag(s)`);
      queryClient.invalidateQueries({ queryKey: ["admin", "rank"] });
    },
    onError: (error) => notify.apiError(error, { title: "Failed to re-enable" })
  });

  const toggleMutation = useMutation({
    mutationFn: async () => {
      const setting = await adminService.getSetting(RANK_KEY);
      const value = { ...(setting.value ?? {}), enabled: !(stats?.enabled ?? false) };
      return adminService.updateSetting(RANK_KEY, { value });
    },
    onSuccess: () => {
      notify.success(stats?.enabled ? "Collection paused" : "Collection resumed");
      queryClient.invalidateQueries({ queryKey: ["admin", "rank", "stats"] });
    },
    onError: (error) => notify.apiError(error, { title: "Failed to update" })
  });

  if (statsQuery.isLoading || !stats) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">Loading collection health…</CardContent>
      </Card>
    );
  }

  const disabled = stats.by_status.disabled;
  const errRate = Math.round(stats.error_rate_24h * 100);
  const errCount = stats.fetch_24h.error + stats.fetch_24h.rate_limited;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium",
              stats.enabled
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                : "border-white/10 bg-white/5 text-white/60"
            )}
          >
            <span className={cn("h-1.5 w-1.5 rounded-full", stats.enabled ? "bg-emerald-400" : "bg-white/40")} />
            {stats.enabled ? "Collecting" : "Paused"}
          </span>
          <span className="text-muted-foreground">
            scope <b className="text-foreground">{stats.scope}</b> · every {formatInterval(stats.interval_seconds)} ·{" "}
            {stats.rate_limit_per_minute}/min
          </span>
        </div>
        <div className="flex items-center gap-2">
          {isSuperuser && (
            <Button variant="outline" size="sm" disabled={toggleMutation.isPending} onClick={() => toggleMutation.mutate()}>
              {toggleMutation.isPending ? (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              ) : stats.enabled ? (
                <Pause className="mr-1.5 h-4 w-4" />
              ) : (
                <Play className="mr-1.5 h-4 w-4" />
              )}
              {stats.enabled ? "Pause" : "Resume"}
            </Button>
          )}
          <Button variant="ghost" size="sm" asChild>
            <Link href="/admin/settings">
              <Settings className="mr-1.5 h-4 w-4" />
              Settings
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardContent className="space-y-3 p-4">
            <div className="flex items-baseline justify-between">
              <span className="text-sm text-muted-foreground">Battle tags</span>
              <span className="text-2xl font-bold tabular-nums">{stats.total}</span>
            </div>
            <StatusBar stats={stats} />
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-1 p-4">
            <span className="text-sm text-muted-foreground">Coverage (snapshots)</span>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold tabular-nums">{stats.coverage_24h}</span>
              <span className="text-sm text-muted-foreground">/ 24h · {pct(stats.coverage_24h, stats.total)}</span>
            </div>
            <p className="text-xs text-muted-foreground">
              7d: <span className="tabular-nums text-foreground">{stats.coverage_7d}</span> distinct accounts
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-1 p-4">
            <span className="text-sm text-muted-foreground">Fetches (24h)</span>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold tabular-nums">{stats.fetch_24h_total}</span>
              <span className={cn("text-sm font-medium", errRate >= 20 ? "text-rose-400" : "text-muted-foreground")}>
                {errRate}% err
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              ok {stats.fetch_24h.ok} · nf {stats.fetch_24h.not_found} · err {errCount}
            </p>
            <p className="text-xs text-muted-foreground">last ✓ {formatRelative(stats.last_success_at)}</p>
          </CardContent>
        </Card>

        <Card className={cn(disabled > 0 && "border-rose-500/40 bg-rose-500/5")}>
          <CardContent className="flex h-full flex-col justify-between gap-2 p-4">
            <div className="flex items-center justify-between">
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 text-sm",
                  disabled > 0 ? "text-rose-300" : "text-muted-foreground"
                )}
              >
                {disabled > 0 && <AlertTriangle className="h-4 w-4" />} Disabled
              </span>
              <span className={cn("text-2xl font-bold tabular-nums", disabled > 0 && "text-rose-300")}>{disabled}</span>
            </div>
            {disabled > 0 ? (
              <Button
                variant="outline"
                size="sm"
                className="border-rose-500/40 text-rose-200 hover:bg-rose-500/10"
                disabled={reenableMutation.isPending}
                onClick={() => reenableMutation.mutate()}
              >
                {reenableMutation.isPending ? (
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                ) : (
                  <RotateCcw className="mr-1.5 h-4 w-4" />
                )}
                Re-enable all
              </Button>
            ) : (
              <p className="text-xs text-muted-foreground">No auto-disabled tags.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
