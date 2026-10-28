"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";

import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { StatTileGridSkeleton } from "@/components/admin/StatTileGridSkeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { usePermissions } from "@/hooks/usePermissions";
import { useFormatter } from "@/lib/datetime/client";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { Spinner } from "@/components/ui/spinner";

import { DistributionBar } from "./DistributionBar";
import {
  STATUS_BAR,
  STATUS_ORDER,
  formatInterval,
  formatRelative,
  rankParsingOutage,
  useRankStatusLabels
} from "./rank-shared";
import { rankCollectionKey } from "./rank-settings";
import { adminQueryKeys } from "@/lib/admin/query-keys";

/** Settings keys naming each collection scope; an unknown scope prints its raw token. */
const SCOPE_KEYS = {
  registrations_only: "collection.scopeRegistrations",
  all: "collection.scopeAll"
} as const;

export function RankHealthDashboard({ discipline }: Readonly<{ discipline: string }>) {
  const t = useTranslations("collectors.rank");
  const tCommon = useTranslations("collectors.common");
  const tSettings = useTranslations("collectors.settings.rank");
  const format = useFormatter();
  const queryClient = useQueryClient();
  const { user } = useAuthProfile();
  const isSuperuser = user?.isSuperuser ?? false;
  const { canAccessPermission } = usePermissions();
  const canReenable = canAccessPermission("rank.update");
  const statusLabels = useRankStatusLabels();
  // The stats are scoped to the workspace `apiFetch` injects, so it belongs in
  // the key — otherwise switching workspace serves the previous tenant's cache.
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const statsQuery = useQuery({
    queryKey: adminQueryKeys.rankStats(workspaceId, discipline),
    queryFn: () => adminService.getRankCollectionStats(discipline),
    refetchInterval: 10000
  });
  const stats = statsQuery.data;

  const reenableMutation = useMutation({
    mutationFn: () => adminService.reenableDisabledRankCollection(discipline, false),
    onSuccess: (result) => {
      notify.success(t("reenabled", { count: result.reenabled }));
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.rank() });
    },
    onError: (error) =>
      notify.apiError(error, { title: t("reenableError") })
  });

  const toggleMutation = useMutation({
    mutationFn: async () => {
      const settingKey = rankCollectionKey(discipline);
      const setting = await adminService.getSetting(settingKey);
      const value = { ...(setting.value ?? {}), enabled: !(stats?.enabled ?? false) };
      return adminService.updateSetting(settingKey, { value });
    },
    onSuccess: () => {
      notify.success(
        tCommon(stats?.enabled ? "collectionPaused" : "collectionResumed")
      );
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.rankStatsAll() });
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

  const disabled = stats.by_status?.disabled ?? 0;
  const errRate = Math.round((stats.error_rate_24h ?? 0) * 100);
  const okCount = stats.fetch_24h?.ok ?? 0;
  const notFoundCount = stats.fetch_24h?.not_found ?? 0;
  const errCount = (stats.fetch_24h?.error ?? 0) + (stats.fetch_24h?.rate_limited ?? 0);
  const invalidTags = stats.invalid_handles_24h ?? 0;
  const outage = rankParsingOutage(stats);
  // A breaker state the backend grows later still renders, as its raw token.
  const circuitKey = `circuit.${stats.upstream_circuit_state ?? "closed"}` as "circuit.closed";
  const circuitState = t.has(circuitKey) ? t(circuitKey) : (stats.upstream_circuit_state ?? "");
  const scope =
    stats.scope in SCOPE_KEYS
      ? tSettings(SCOPE_KEYS[stats.scope as keyof typeof SCOPE_KEYS])
      : stats.scope;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Polls every 10s — announce the pause/resume flip and the pacing. */}
        <output className="text-sm text-muted-foreground">
          {stats.enabled
            ? t.rich("pace", {
                scope,
                interval: formatInterval(format, stats.interval_seconds),
                rate: stats.rate_limit_per_minute,
                b: (chunks) => <b className="text-foreground">{chunks}</b>,
                num: (chunks) => <span className="tabular-nums">{chunks}</span>
              })
            : tCommon("health.paused")}
        </output>
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

      {/* The failure this page used to hide: with the circuit open or the
          collector stalled, every tile below reads healthy-but-stale, because
          the numbers describe fetches that stopped happening. */}
      {outage && (
        <Alert tone="danger">
          <AlertTriangle aria-hidden className="h-4 w-4" />
          <AlertTitle>{t("outage.title")}</AlertTitle>
          <AlertDescription>
            {outage.reason === "circuit_open"
              ? t("outage.circuitOpen", {
                  host: stats.upstream_base_url || t("outage.hostFallback")
                })
              : t("outage.stale", { since: formatRelative(format, stats.last_success_at) })}{" "}
            {t("outage.action", { host: stats.upstream_base_url || t("outage.hostFallback") })}
          </AlertDescription>
        </Alert>
      )}

      <StatTileGrid className="xl:grid-cols-5">
        <StatTile label={t("tiles.battleTags")} value={stats.total} />

        <StatTile
          label={t("tiles.coverage")}
          value={stats.coverage_24h}
          detail={t("tiles.coverageDetail", {
            percent: stats.total ? Math.round((stats.coverage_24h / stats.total) * 100) : 0,
            week: stats.coverage_7d
          })}
        />

        <StatTile
          label={t("tiles.fetches")}
          value={stats.fetch_24h_total ?? 0}
          detail={t("tiles.fetchesDetail", {
            rate: errRate,
            ok: okCount,
            notFound: notFoundCount,
            errors: errCount,
            last: formatRelative(format, stats.last_success_at)
          })}
          tone={errRate >= 20 ? "danger" : "neutral"}
          icon={errRate >= 20 ? AlertTriangle : undefined}
        />

        <StatTile
          label={t("tiles.upstream")}
          value={outage?.reason === "circuit_open" ? t("tiles.upstreamUnreachable") : circuitState}
          detail={t("tiles.upstreamDetail", {
            host: stats.upstream_base_url || t("tiles.upstreamNotConfigured"),
            count: invalidTags
          })}
          tone={outage || invalidTags > 0 ? "danger" : "neutral"}
          icon={outage || invalidTags > 0 ? AlertTriangle : undefined}
        />

        <StatTile
          label={t("tiles.autoDisabled")}
          value={disabled}
          tone={disabled > 0 ? "danger" : "neutral"}
          action={
            disabled > 0 && canReenable ? (
              <Button
                variant="outline"
                size="sm"
                disabled={reenableMutation.isPending}
                onClick={() => reenableMutation.mutate()}
              >
                {reenableMutation.isPending ? <Spinner className="mr-1.5" /> : null}
                {t("tiles.reenableAll")}
              </Button>
            ) : undefined
          }
        />
      </StatTileGrid>

      <DistributionBar
        order={STATUS_ORDER}
        counts={stats.by_status}
        total={stats.total}
        labels={statusLabels}
        fills={STATUS_BAR}
      />
    </div>
  );
}
