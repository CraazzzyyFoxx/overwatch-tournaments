"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { AlertTriangle, Pause, Play, RotateCcw } from "lucide-react";

import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { StatTileGridSkeleton } from "@/components/admin/StatTileGridSkeleton";
import { TintedBadge } from "@/components/admin/TintedBadge";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useFormatter } from "@/lib/datetime/client";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { RankCollectionStats } from "@/types/admin.types";
import { Spinner } from "@/components/ui/spinner";

import { RUN_STATE_TONES } from "./collector-state";
import {
  STATUS_BAR,
  STATUS_ORDER,
  formatInterval,
  formatRelative,
  rankParsingOutage,
  useRankStatusLabels
} from "./rank-shared";
import { adminQueryKeys } from "@/lib/admin/query-keys";

const RANK_SETTING_KEY = "parser.rank_collection";

/**
 * Stacked distribution of battle tags per collection status.
 *
 * The bar is `aria-hidden`: the legend directly under it repeats every segment
 * as `<status> <count>` text, so the state is never carried by colour alone.
 */
function StatusBar({ stats }: Readonly<{ stats: RankCollectionStats }>) {
  const labels = useRankStatusLabels();
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
              title={`${labels[s]}: ${counts[s]}`}
            />
          ) : null
        )}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
        {STATUS_ORDER.map((s) =>
          counts[s] ? (
            <span key={s} className="inline-flex items-center gap-1.5 text-muted-foreground">
              <span aria-hidden className={cn("h-2 w-2 rounded-full", STATUS_BAR[s])} />
              {labels[s]} <span className="tabular-nums text-foreground">{counts[s]}</span>
            </span>
          ) : null
        )}
      </div>
    </div>
  );
}

export function RankHealthDashboard() {
  const t = useTranslations("collectors.rank");
  const tCommon = useTranslations("collectors.common");
  const format = useFormatter();
  const queryClient = useQueryClient();
  const { user } = useAuthProfile();
  const isSuperuser = user?.isSuperuser ?? false;
  // The stats are scoped to the workspace `apiFetch` injects, so it belongs in
  // the key — otherwise switching workspace serves the previous tenant's cache.
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const statsQuery = useQuery({
    queryKey: adminQueryKeys.rankStats(workspaceId),
    queryFn: () => adminService.getRankCollectionStats(),
    refetchInterval: 10000
  });
  const stats = statsQuery.data;

  const reenableMutation = useMutation({
    mutationFn: () => adminService.reenableDisabledRankCollection(false),
    onSuccess: (result) => {
      notify.success(t("reenabled", { count: result.reenabled }));
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.rank() });
    },
    onError: (error) =>
      notify.apiError(error, { title: t("reenableError") })
  });

  const toggleMutation = useMutation({
    mutationFn: async () => {
      const setting = await adminService.getSetting(RANK_SETTING_KEY);
      const value = { ...(setting.value ?? {}), enabled: !(stats?.enabled ?? false) };
      return adminService.updateSetting(RANK_SETTING_KEY, { value });
    },
    onSuccess: () => {
      notify.success(
        tCommon(stats?.enabled ? "collectionPaused" : "collectionResumed")
      );
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.rankStatsAll() });
    },
    onError: (error) =>
      notify.apiError(error, { title: tCommon("collectionToggleError") })
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
  // A breaker state the backend grows later still renders, as its raw token.
  const circuitKey = `circuit.${stats.overfast_circuit_state ?? "closed"}` as "circuit.closed";
  const circuitState = t.has(circuitKey) ? t(circuitKey) : (stats.overfast_circuit_state ?? "");
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Polls every 10s — announce the pause/resume flip and the pacing. */}
        <output className="flex flex-wrap items-center gap-2 text-sm">
          <TintedBadge
            value={stats.enabled ? "running" : "paused"}
            tones={RUN_STATE_TONES}
            labels={{ running: t("run.collecting"), paused: tCommon("health.paused") }}
            fallback={tCommon("health.paused")}
            dot
          />
          <span className="text-muted-foreground">
            {t.rich("pace", {
              scope: stats.scope,
              interval: formatInterval(format, stats.interval_seconds),
              rate: stats.rate_limit_per_minute,
              b: (chunks) => <b className="text-foreground">{chunks}</b>,
              num: (chunks) => <span className="tabular-nums">{chunks}</span>
            })}
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
              <Spinner className="mr-1.5" />
            ) : stats.enabled ? (
              <Pause aria-hidden className="mr-1.5 h-4 w-4" />
            ) : (
              <Play aria-hidden className="mr-1.5 h-4 w-4" />
            )}
            {tCommon(stats.enabled ? "pauseCollection" : "resumeCollection")}
          </Button>
        )}
      </div>

      {/* The failure this page used to hide: with the circuit open or the
          collector stalled, every tile below reads healthy-but-stale, because
          the numbers describe fetches that stopped happening. */}
      {outage && (
        <Alert variant="destructive">
          <AlertTriangle aria-hidden className="h-4 w-4" />
          <AlertTitle>{t("outage.title")}</AlertTitle>
          <AlertDescription>
            {outage.reason === "circuit_open"
              ? t("outage.circuitOpen", {
                  host: stats.overfast_base_url || t("outage.hostFallback")
                })
              : t("outage.stale", { since: formatRelative(format, stats.last_success_at) })}{" "}
            {t("outage.action", { host: stats.overfast_base_url || t("outage.hostFallback") })}
          </AlertDescription>
        </Alert>
      )}

      <StatTileGrid className="xl:grid-cols-5">
        {/* Not a StatTile: the tile owns a stacked distribution bar below the value. */}
        <div className="space-y-3 rounded-xl border border-border/60 bg-card/70 p-4">
          <div className="flex items-baseline justify-between gap-3">
            <p className={EYEBROW_CLASS}>{t("tiles.battleTags")}</p>
            <p className="text-2xl font-semibold tabular-nums">{stats.total}</p>
          </div>
          <StatusBar stats={stats} />
        </div>

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
            host: stats.overfast_base_url || t("tiles.upstreamNotConfigured"),
            count: invalidTags
          })}
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
            <p className={cn(EYEBROW_CLASS, disabled > 0 && "text-danger")}>
              {t("tiles.autoDisabled")}
            </p>
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
                <Spinner className="mr-1.5" />
              ) : (
                <RotateCcw aria-hidden className="mr-1.5 h-4 w-4" />
              )}
              {t("tiles.reenableAll")}
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">{t("tiles.noneDisabled")}</p>
          )}
        </div>
      </StatTileGrid>
    </div>
  );
}
