"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Pause, Play, RefreshCw } from "lucide-react";

import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { StatTileGridSkeleton } from "@/components/admin/StatTileGridSkeleton";
import { TintedBadge } from "@/components/admin/TintedBadge";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Button } from "@/components/ui/button";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { SubscriptionCollectionStats } from "@/types/admin.types";
import { Spinner } from "@/components/ui/spinner";

import { RUN_STATE_TONES } from "./collector-state";
import {
  PROVIDER_LABELS,
  STATE_BAR,
  STATE_LABELS,
  STATE_ORDER,
  formatInterval,
  formatRelative
} from "./subscription-shared";

const SUBSCRIPTION_KEY = "parser.subscription_collection";

/**
 * Stacked distribution of entitlements per state.
 *
 * The bar is `aria-hidden`: the legend directly under it repeats every segment
 * as `<state> <count>` text, so the state is never carried by colour alone.
 */
function StateBar({ stats }: Readonly<{ stats: SubscriptionCollectionStats }>) {
  const total = stats.total || 1;
  const counts = stats.by_state ?? {};
  return (
    <div className="space-y-2">
      <div aria-hidden className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted/20">
        {STATE_ORDER.map((s) =>
          counts[s] ? (
            <div
              key={s}
              className={cn("h-full", STATE_BAR[s])}
              style={{ width: `${(counts[s] / total) * 100}%` }}
              title={`${s}: ${counts[s]}`}
            />
          ) : null
        )}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
        {STATE_ORDER.map((s) =>
          counts[s] ? (
            <span key={s} className="inline-flex items-center gap-1.5 text-muted-foreground">
              <span aria-hidden className={cn("h-2 w-2 rounded-full", STATE_BAR[s])} />
              {STATE_LABELS[s] ?? s} <span className="tabular-nums text-foreground">{counts[s]}</span>
            </span>
          ) : null
        )}
      </div>
    </div>
  );
}

export function SubscriptionHealthDashboard() {
  const queryClient = useQueryClient();
  const { user } = useAuthProfile();
  const isSuperuser = user?.isSuperuser ?? false;
  // The stats are scoped to the workspace `apiFetch` injects, so it belongs in
  // the key — otherwise switching workspace serves the previous tenant's cache.
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const statsQuery = useQuery({
    queryKey: ["admin", "subscriptions", "stats", workspaceId],
    queryFn: () => adminService.getSubscriptionCollectionStats(),
    refetchInterval: 10000
  });
  const stats = statsQuery.data;

  const sweepMutation = useMutation({
    // No `user_id` = sweep every open tournament that requires a subscription.
    mutationFn: () => adminService.triggerSubscriptionCollection({}),
    onSuccess: (result) => {
      notify.success(
        result.checked === 1 ? "Checked 1 subscription" : `Checked ${result.checked} subscriptions`
      );
      queryClient.invalidateQueries({ queryKey: ["admin", "subscriptions"] });
    },
    onError: (error) =>
      notify.apiError(error, { title: "Could not run the subscription sweep — try again" })
  });

  const toggleMutation = useMutation({
    mutationFn: async () => {
      const setting = await adminService.getSetting(SUBSCRIPTION_KEY);
      const value = { ...(setting.value ?? {}), enabled: !(stats?.enabled ?? false) };
      return adminService.updateSetting(SUBSCRIPTION_KEY, { value });
    },
    onSuccess: () => {
      notify.success(stats?.enabled ? "Collection paused" : "Collection resumed");
      queryClient.invalidateQueries({ queryKey: ["admin", "subscriptions", "stats"] });
    },
    onError: (error) =>
      notify.apiError(error, { title: "Could not change the collection state — try again" })
  });

  if (statsQuery.isLoading || !stats) {
    return <StatTileGridSkeleton />;
  }

  const errRate = Math.round((stats.error_rate_24h ?? 0) * 100);
  const activeCount = stats.checks_24h?.active ?? 0;
  const inactiveCount = stats.checks_24h?.inactive ?? 0;
  // `unknown` and `error` both mean "the check did not conclude" — a provider
  // outage and a misconfiguration read the same to the operator here.
  const failedCount = (stats.checks_24h?.unknown ?? 0) + (stats.checks_24h?.error ?? 0);
  const providers = Object.entries(stats.by_provider ?? {});

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
            <span className="tabular-nums">{stats.active_tournaments}</span>{" "}
            {stats.active_tournaments === 1 ? "tournament" : "tournaments"} gated · every{" "}
            <span className="tabular-nums">{formatInterval(stats.interval_seconds)}</span> ·{" "}
            <span className="tabular-nums">{stats.batch_size}</span>/batch
          </span>
        </output>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={sweepMutation.isPending}
            onClick={() => sweepMutation.mutate()}
          >
            {sweepMutation.isPending ? (
              <Spinner className="mr-1.5" />
            ) : (
              <RefreshCw aria-hidden className="mr-1.5 h-4 w-4" />
            )}
            Check all now
          </Button>
          {isSuperuser && (
            <Button
              variant="outline"
              size="sm"
              disabled={toggleMutation.isPending}
              onClick={() => toggleMutation.mutate()}
            >
              {toggleMutation.isPending ? (
                <Spinner className="mr-1.5" />
              ) : stats.enabled ? (
                <Pause aria-hidden className="mr-1.5 h-4 w-4" />
              ) : (
                <Play aria-hidden className="mr-1.5 h-4 w-4" />
              )}
              {stats.enabled ? "Pause collection" : "Resume collection"}
            </Button>
          )}
        </div>
      </div>

      <StatTileGrid>
        {/* Not a StatTile: the tile owns a stacked distribution bar below the value. */}
        <div className="space-y-3 rounded-xl border border-border/60 bg-card/70 p-4">
          <div className="flex items-baseline justify-between gap-3">
            <p className={EYEBROW_CLASS}>Entitlements</p>
            <p className="text-2xl font-semibold tabular-nums">{stats.total}</p>
          </div>
          <StateBar stats={stats} />
        </div>

        <StatTile
          label="Players tracked"
          value={stats.tracked_users}
          detail={`${stats.never_checked} never checked · ${
            providers.length
              ? providers.map(([p, n]) => `${PROVIDER_LABELS[p] ?? p} ${n}`).join(" · ")
              : "no providers yet"
          }`}
        />

        <StatTile
          label="Coverage (checked)"
          value={stats.coverage_24h}
          detail={`${stats.coverage_24h} distinct players in 24h · ${stats.coverage_7d} in 7d · last check ${formatRelative(stats.last_check_at)}`}
        />

        <StatTile
          label="Checks (24h)"
          value={stats.checks_24h_total ?? 0}
          detail={`${errRate}% unresolved · active ${activeCount} · inactive ${inactiveCount} · unresolved ${failedCount} · last active ${formatRelative(stats.last_success_at)}`}
          tone={errRate >= 20 ? "danger" : "neutral"}
          icon={errRate >= 20 ? AlertTriangle : undefined}
        />
      </StatTileGrid>
    </div>
  );
}
