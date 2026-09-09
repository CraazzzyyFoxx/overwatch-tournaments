"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2, Pause, Play, RotateCcw } from "lucide-react";

import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { StatTileGridSkeleton } from "@/components/admin/StatTileGridSkeleton";
import { TintedBadge } from "@/components/admin/TintedBadge";
import { EYEBROW_CLASS } from "@/components/admin/tone";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { RankCollectionStats } from "@/types/admin.types";

import { RUN_STATE_TONES } from "./collector-state";
import {
  STATUS_BAR,
  STATUS_ORDER,
  formatInterval,
  formatRelative,
  rankParsingOutage
} from "./rank-shared";

const RANK_SETTING_KEY = "parser.rank_collection";

/**
 * Stacked distribution of battle tags per collection status.
 *
 * The bar is `aria-hidden`: the legend directly under it repeats every segment
 * as `<status> <count>` text, so the state is never carried by colour alone.
 */
function StatusBar({ stats }: Readonly<{ stats: RankCollectionStats }>) {
  const total = stats.total || 1;
  const counts = stats.by_status || {};
  return (
    <div className="space-y-2">
      <div aria-hidden className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted/20">
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
              <span aria-hidden className={cn("h-2 w-2 rounded-full", STATUS_BAR[s])} />
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
  // The stats are scoped to the workspace `apiFetch` injects, so it belongs in
  // the key — otherwise switching workspace serves the previous tenant's cache.
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const statsQuery = useQuery({
    queryKey: ["admin", "rank", "stats", workspaceId],
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
    onError: (error) =>
      notify.apiError(error, { title: "Could not re-enable the disabled tags — try again" })
  });

  const toggleMutation = useMutation({
    mutationFn: async () => {
      const setting = await adminService.getSetting(RANK_SETTING_KEY);
      const value = { ...(setting.value ?? {}), enabled: !(stats?.enabled ?? false) };
      return adminService.updateSetting(RANK_SETTING_KEY, { value });
    },
    onSuccess: () => {
      notify.success(stats?.enabled ? "Collection paused" : "Collection resumed");
      queryClient.invalidateQueries({ queryKey: ["admin", "rank", "stats"] });
    },
    onError: (error) =>
      notify.apiError(error, { title: "Could not change the collection state — try again" })
  });

  if (statsQuery.isLoading || !stats) {
    return <StatTileGridSkeleton />;
  }

  const disabled = stats.by_status?.disabled ?? 0;
  const errRate = Math.round((stats.error_rate_24h ?? 0) * 100);
  const okCount = stats.fetch_24h?.ok ?? 0;
  const notFoundCount = stats.fetch_24h?.not_found ?? 0;
  const errCount = (stats.fetch_24h?.error ?? 0) + (stats.fetch_24h?.rate_limited ?? 0);
  const invalidTags = stats.invalid_battle_tags_24h ?? 0;
  const outage = rankParsingOutage(stats);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Polls every 10s — announce the pause/resume flip and the pacing. */}
        <output className="flex flex-wrap items-center gap-2 text-sm">
          <TintedBadge
            value={stats.enabled ? "running" : "paused"}
            tones={RUN_STATE_TONES}
            labels={{ running: "Collecting", paused: "Paused" }}
            fallback="Paused"
            dot
          />
          <span className="text-muted-foreground">
            scope <b className="text-foreground">{stats.scope}</b> · every{" "}
            <span className="tabular-nums">{formatInterval(stats.interval_seconds)}</span> ·{" "}
            <span className="tabular-nums">{stats.rate_limit_per_minute}</span>/min
          </span>
        </output>
        {isSuperuser && (
          <Button
            variant="outline"
            size="sm"
            disabled={toggleMutation.isPending}
            onClick={() => toggleMutation.mutate()}
          >
            {toggleMutation.isPending ? (
              <Loader2 aria-hidden className="mr-1.5 h-4 w-4 animate-spin motion-reduce:animate-none" />
            ) : stats.enabled ? (
              <Pause aria-hidden className="mr-1.5 h-4 w-4" />
            ) : (
              <Play aria-hidden className="mr-1.5 h-4 w-4" />
            )}
            {stats.enabled ? "Pause collection" : "Resume collection"}
          </Button>
        )}
      </div>

      {/* The failure this page used to hide: with the circuit open or the
          collector stalled, every tile below reads healthy-but-stale, because
          the numbers describe fetches that stopped happening. */}
      {outage && (
        <Alert variant="destructive">
          <AlertTriangle aria-hidden className="h-4 w-4" />
          <AlertTitle>Battle-tag rank parsing is down</AlertTitle>
          <AlertDescription>
            {outage.reason === "circuit_open"
              ? `The circuit breaker to ${stats.overfast_base_url || "OverFast"} is open — every fetch is refused inside the worker, so the counters below stopped moving instead of reporting errors.`
              : `No battle tag has been collected successfully since ${formatRelative(stats.last_success_at)}, although collection is switched on.`}{" "}
            Check that {stats.overfast_base_url || "the OverFast instance"} resolves and answers, then watch this
            banner clear on the next tick.
          </AlertDescription>
        </Alert>
      )}

      <StatTileGrid>
        {/* Not a StatTile: the tile owns a stacked distribution bar below the value. */}
        <div className="space-y-3 rounded-xl border border-border/60 bg-card/70 p-4">
          <div className="flex items-baseline justify-between gap-3">
            <p className={EYEBROW_CLASS}>Battle tags</p>
            <p className="text-2xl font-semibold tabular-nums">{stats.total}</p>
          </div>
          <StatusBar stats={stats} />
        </div>

        <StatTile
          label="Coverage (snapshots)"
          value={stats.coverage_24h}
          detail={`${stats.total ? Math.round((stats.coverage_24h / stats.total) * 100) : 0}% of all tags in 24h · ${stats.coverage_7d} distinct accounts in 7d`}
        />

        <StatTile
          label="Fetches (24h)"
          value={stats.fetch_24h_total ?? 0}
          detail={`${errRate}% errors · ok ${okCount} · not found ${notFoundCount} · errors ${errCount} · last success ${formatRelative(stats.last_success_at)}`}
          tone={errRate >= 20 ? "danger" : "neutral"}
          icon={errRate >= 20 ? AlertTriangle : undefined}
        />

        <StatTile
          label="Upstream (OverFast)"
          value={outage?.reason === "circuit_open" ? "unreachable" : (stats.overfast_circuit_state ?? "closed")}
          detail={`${stats.overfast_base_url || "not configured"} · ${invalidTags} malformed battle tag(s) rejected in 24h`}
          tone={outage || invalidTags > 0 ? "danger" : "neutral"}
          icon={outage || invalidTags > 0 ? AlertTriangle : undefined}
        />

        {/* Not a StatTile: the tile owns the bulk re-enable action. */}
        <div
          className={cn(
            "flex flex-col justify-between gap-2 rounded-xl border p-4",
            disabled > 0 ? "border-danger/40 bg-danger/10" : "border-border/60 bg-card/70"
          )}
        >
          <div className="flex items-baseline justify-between gap-3">
            <p className={cn(EYEBROW_CLASS, disabled > 0 && "text-danger")}>Auto-disabled tags</p>
            <p className={cn("text-2xl font-semibold tabular-nums", disabled > 0 && "text-danger")}>
              {disabled}
            </p>
          </div>
          {disabled > 0 ? (
            <Button
              variant="outline"
              size="sm"
              className="border-danger/40 text-danger hover:bg-danger/10"
              disabled={reenableMutation.isPending}
              onClick={() => reenableMutation.mutate()}
            >
              {reenableMutation.isPending ? (
                <Loader2 aria-hidden className="mr-1.5 h-4 w-4 animate-spin motion-reduce:animate-none" />
              ) : (
                <RotateCcw aria-hidden className="mr-1.5 h-4 w-4" />
              )}
              Re-enable all tags
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">
              No tags disabled after repeated fetch failures.
            </p>
          )}
        </div>
      </StatTileGrid>
    </div>
  );
}
