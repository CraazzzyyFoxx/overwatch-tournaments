"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { AlertTriangle, Clock, Gauge, Radio, Trophy } from "lucide-react";

import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { StatTileGridSkeleton } from "@/components/admin/StatTileGridSkeleton";
import { formatInterval, formatRelative } from "@/components/kit/format-time";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useFormatter } from "@/lib/datetime/client";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import { Spinner } from "@/components/ui/spinner";

import { diagnoseStreamHealth } from "./stream-shared";
import { adminQueryKeys } from "@/lib/admin/query-keys";

const STREAM_KEY = "stream.collection";

// The tick itself runs no faster than 30s (the setting's floor), so polling the
// panel harder than that only re-renders the same numbers. Matches the
// rank/subscription dashboards in kind, not in value: their sweeps are minutes
// apart, this one is seconds.
const REFETCH_MS = 30_000;

export function StreamHealthDashboard() {
  const t = useTranslations("collectors.streams");
  const tCommon = useTranslations("collectors.common");
  const format = useFormatter();
  const queryClient = useQueryClient();
  const { user } = useAuthProfile();
  const isSuperuser = user?.isSuperuser ?? false;

  // No workspace in the key: one poller, one Redis key, one set of numbers.
  const healthQuery = useQuery({
    queryKey: adminQueryKeys.streamsHealth(),
    queryFn: () => adminService.getStreamPollHealth(),
    refetchInterval: REFETCH_MS
  });
  const health = healthQuery.data;

  const toggleMutation = useMutation({
    mutationFn: async () => {
      const setting = await adminService.getSetting(STREAM_KEY);
      const value = { ...(setting.value ?? {}), enabled: !(health?.enabled ?? false) };
      return adminService.updateSetting(STREAM_KEY, { value });
    },
    onSuccess: () => {
      notify.success(t(health?.enabled ? "pollingPaused" : "pollingResumed"));
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.streams() });
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.settings() });
    },
    onError: (error) =>
      notify.apiError(error, { title: t("pollingToggleError") })
  });

  if (!health) {
    return healthQuery.isError ? (
      <PageStateCard state="error" onAction={() => healthQuery.refetch()} />
    ) : (
      <StatTileGridSkeleton />
    );
  }

  const diagnosis = diagnoseStreamHealth(health);
  // Only a problem earns the banner; a healthy, idle or paused poller is said
  // by the tab dot, the Last tick tile and the pause button.
  const alerting = diagnosis.tone === "danger" || diagnosis.tone === "warning";
  // Only the alerting states carry a hint.
  const hintKey = `status.${diagnosis.key}.hint` as "status.error.hint";
  // 800/min shared with identity-service sign-ins; a low reading is a sign-in
  // outage waiting to happen, so it is worth a tone rather than a bare number.
  const remaining = health.ratelimit_remaining;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Refetches every 30s — announce the pause/resume flip and the pacing. */}
        <output className="text-sm text-muted-foreground">
          {health.enabled
            ? t.rich("pace", {
                interval: formatInterval(format, health.interval_seconds),
                batch: health.batch_size,
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
            {t(health.enabled ? "pausePolling" : "resumePolling")}
          </Button>
        )}
      </div>

      {alerting && (
        <Alert tone={diagnosis.tone}>
          <AlertTriangle aria-hidden className="h-4 w-4" />
          <AlertTitle>{t(`status.${diagnosis.key}.label`)}</AlertTitle>
          {t.has(hintKey) ? <AlertDescription>{t(hintKey)}</AlertDescription> : null}
        </Alert>
      )}

      <StatTileGrid className="xl:grid-cols-5">
        <StatTile
          label={t("tiles.lastTick")}
          value={
            health.last_run_at ? formatRelative(format, health.last_run_at) : t("tiles.neverRun")
          }
          detail={health.status ? t(`status.${health.status}.label`) : undefined}
          icon={Clock}
        />

        <StatTile
          label={t("tiles.tournaments")}
          value={health.tournaments_active ?? ""}
          detail={t("tiles.tournamentsDetail", { count: health.tournaments_updated ?? 0 })}
          icon={Trophy}
        />

        <StatTile
          label={t("tiles.channels")}
          value={health.channels_polled ?? ""}
          detail={t("tiles.channelsDetail")}
          icon={Radio}
        />

        <StatTile
          label={t("tiles.live")}
          value={health.live_channels ?? ""}
          detail={t("tiles.liveDetail")}
          icon={Radio}
        />

        <StatTile
          label={t("tiles.rateLimit")}
          value={remaining ?? ""}
          detail={t("tiles.rateLimitDetail")}
          icon={Gauge}
          tone={remaining != null && remaining < 80 ? "danger" : "neutral"}
        />
      </StatTileGrid>
    </div>
  );
}
