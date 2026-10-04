"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { AlertTriangle, Clock, Gauge, Pause, Play, Radio, Trophy } from "lucide-react";

import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { StatTileGridSkeleton } from "@/components/admin/StatTileGridSkeleton";
import { TintedBadge } from "@/components/admin/TintedBadge";
import { formatInterval, formatRelative } from "@/components/kit/format-time";
import { TONE_CLASS, type Tone } from "@/components/kit/tone";
import { Button } from "@/components/ui/button";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useFormatter } from "@/lib/datetime/client";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import { Spinner } from "@/components/ui/spinner";

import { RUN_STATE_TONES } from "./collector-state";
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

  if (healthQuery.isLoading || !health) {
    return <StatTileGridSkeleton />;
  }

  const diagnosis = diagnoseStreamHealth(health);
  const hint = t(`status.${diagnosis.key}.hint`);
  // 800/min shared with identity-service sign-ins; a low reading is a sign-in
  // outage waiting to happen, so it is worth a tone rather than a bare number.
  const remaining = health.ratelimit_remaining;
  const rateTone: Tone = remaining == null ? "neutral" : remaining < 80 ? "danger" : "neutral";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Refetches every 30s — announce the pause/resume flip and the pacing. */}
        <output className="flex flex-wrap items-center gap-2 text-sm">
          <TintedBadge
            value={health.enabled ? "running" : "paused"}
            tones={RUN_STATE_TONES}
            labels={{ running: t("run.polling"), paused: tCommon("health.paused") }}
            fallback={tCommon("health.paused")}
            dot
          />
          <span className="text-muted-foreground">
            {t.rich("pace", {
              interval: formatInterval(format, health.interval_seconds),
              batch: health.batch_size,
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
            ) : health.enabled ? (
              <Pause aria-hidden className="mr-1.5 h-4 w-4" />
            ) : (
              <Play aria-hidden className="mr-1.5 h-4 w-4" />
            )}
            {t(health.enabled ? "pausePolling" : "resumePolling")}
          </Button>
        )}
      </div>

      <div className={cn("space-y-1 rounded-xl border p-4 text-sm", TONE_CLASS[diagnosis.tone])}>
        <p className="flex items-center gap-2 font-medium">
          {diagnosis.tone === "danger" || diagnosis.tone === "warning" ? (
            <AlertTriangle aria-hidden className="h-4 w-4 shrink-0" />
          ) : null}
          {t(`status.${diagnosis.key}.label`)}
        </p>
        {hint ? (
          <p className="text-muted-foreground">{hint}</p>
        ) : (
          <p className="text-muted-foreground">
            {t("nothingToDo", { time: formatRelative(format, health.last_run_at) })}
          </p>
        )}
      </div>

      <StatTileGrid className="xl:grid-cols-5">
        <StatTile
          label={t("tiles.lastTick")}
          value={formatRelative(format, health.last_run_at)}
          detail={
            health.status === null ? t("tiles.neverRun") : t(`status.${health.status}.label`)
          }
          icon={Clock}
          tone={diagnosis.tone}
        />

        <StatTile
          label={t("tiles.tournaments")}
          value={health.tournaments_active ?? "—"}
          detail={t("tiles.tournamentsDetail", { count: health.tournaments_updated ?? 0 })}
          icon={Trophy}
        />

        <StatTile
          label={t("tiles.channels")}
          value={health.channels_polled ?? "—"}
          detail={t("tiles.channelsDetail")}
          icon={Radio}
        />

        <StatTile
          label={t("tiles.live")}
          value={health.live_channels ?? "—"}
          detail={t("tiles.liveDetail")}
          icon={Radio}
          tone={(health.live_channels ?? 0) > 0 ? "success" : "neutral"}
        />

        <StatTile
          label={t("tiles.rateLimit")}
          value={remaining ?? "—"}
          detail={t("tiles.rateLimitDetail")}
          icon={Gauge}
          tone={rateTone}
        />
      </StatTileGrid>
    </div>
  );
}
