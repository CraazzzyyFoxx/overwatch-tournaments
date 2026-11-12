"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";

import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { StatTileGridSkeleton } from "@/components/admin/StatTileGridSkeleton";
import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { usePermissions } from "@/hooks/usePermissions";
import { useFormatter } from "@/lib/datetime/client";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";

import { DistributionBar } from "./DistributionBar";
import {
  PROVIDER_LABELS,
  STATE_BAR,
  STATE_ORDER,
  formatInterval,
  formatRelative,
  useSubscriptionLabels
} from "./subscription-shared";
import { adminQueryKeys } from "@/lib/admin/query-keys";

const SUBSCRIPTION_KEY = "parser.subscription_collection";

export function SubscriptionHealthDashboard() {
  const t = useTranslations("collectors.subscriptions");
  const tCommon = useTranslations("collectors.common");
  const format = useFormatter();
  const queryClient = useQueryClient();
  const { user } = useAuthProfile();
  const isSuperuser = user?.isSuperuser ?? false;
  const { canAccessPermission } = usePermissions();
  const canSweep = canAccessPermission("subscription.update");
  const labels = useSubscriptionLabels();
  // The stats are scoped to the workspace `apiFetch` injects, so it belongs in
  // the key — otherwise switching workspace serves the previous tenant's cache.
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const statsQuery = useQuery({
    queryKey: adminQueryKeys.subscriptionsStats(workspaceId),
    queryFn: () => adminService.getSubscriptionCollectionStats(),
    refetchInterval: 10000
  });
  const stats = statsQuery.data;

  const sweepMutation = useMutation({
    // No `user_id` = sweep every open tournament that requires a subscription.
    mutationFn: () => adminService.triggerSubscriptionCollection({}),
    onSuccess: (result) => {
      notify.success(t("swept", { count: result.checked }));
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.subscriptions() });
    },
    onError: (error) =>
      notify.apiError(error, { title: t("sweepError") })
  });

  const toggleMutation = useMutation({
    mutationFn: async () => {
      const setting = await adminService.getSetting(SUBSCRIPTION_KEY);
      const value = { ...(setting.value ?? {}), enabled: !(stats?.enabled ?? false) };
      return adminService.updateSetting(SUBSCRIPTION_KEY, { value });
    },
    onSuccess: () => {
      notify.success(tCommon(stats?.enabled ? "collectionPaused" : "collectionResumed"));
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.subscriptionsStatsAll() });
      // The Settings slot saves the whole value, `enabled` included: it must
      // not save back the state this button just flipped.
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.settings() });
    },
    onError: (error) =>
      notify.apiError(error, { title: tCommon("collectionToggleError") })
  });

  if (!stats) {
    return statsQuery.isError ? (
      <PageStateCard state="error" onAction={() => statsQuery.refetch()} />
    ) : (
      <StatTileGridSkeleton />
    );
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
        <output className="text-sm text-muted-foreground">
          {stats.enabled
            ? t.rich("pace", {
                count: stats.active_tournaments,
                interval: formatInterval(format, stats.interval_seconds),
                batch: stats.batch_size,
                num: (chunks) => <span className="tabular-nums">{chunks}</span>
              })
            : tCommon("health.paused")}
        </output>
        <div className="flex items-center gap-2">
          {canSweep && (
            <Button
              variant="outline"
              size="sm"
              disabled={sweepMutation.isPending}
              onClick={() => sweepMutation.mutate()}
            >
              {sweepMutation.isPending ? <Spinner className="mr-1.5" /> : null}
              {t("checkAll")}
            </Button>
          )}
          {isSuperuser && (
            <Button
              variant="outline"
              size="sm"
              disabled={toggleMutation.isPending}
              onClick={() => toggleMutation.mutate()}
            >
              {toggleMutation.isPending ? <Spinner className="mr-1.5" /> : null}
              {tCommon(stats.enabled ? "pauseCollection" : "resumeCollection")}
            </Button>
          )}
        </div>
      </div>

      <StatTileGrid>
        <StatTile label={t("tiles.entitlements")} value={stats.total} />

        <StatTile
          label={t("tiles.tracked")}
          value={stats.tracked_users}
          detail={t("tiles.trackedDetail", {
            never: stats.never_checked,
            providers: providers.length
              ? providers.map(([p, n]) => `${PROVIDER_LABELS[p] ?? p} ${n}`).join(" · ")
              : t("tiles.noProviders")
          })}
        />

        <StatTile
          label={t("tiles.coverage")}
          value={stats.coverage_24h}
          detail={t("tiles.coverageDetail", {
            day: stats.coverage_24h,
            week: stats.coverage_7d,
            last: formatRelative(format, stats.last_check_at)
          })}
        />

        <StatTile
          label={t("tiles.checks")}
          value={stats.checks_24h_total ?? 0}
          detail={t("tiles.checksDetail", {
            rate: errRate,
            active: activeCount,
            inactive: inactiveCount,
            failed: failedCount,
            last: formatRelative(format, stats.last_success_at)
          })}
          tone={errRate >= 20 ? "danger" : "neutral"}
          icon={errRate >= 20 ? AlertTriangle : undefined}
        />
      </StatTileGrid>

      <DistributionBar
        order={STATE_ORDER}
        counts={stats.by_state}
        total={stats.total}
        labels={labels.state}
        fills={STATE_BAR}
      />
    </div>
  );
}
