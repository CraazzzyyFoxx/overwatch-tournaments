"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Clock, Gauge, Pause, Play, Radio, Trophy } from "lucide-react";

import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { StatTileGridSkeleton } from "@/components/admin/StatTileGridSkeleton";
import { TintedBadge } from "@/components/admin/TintedBadge";
import { formatInterval, formatRelative } from "@/components/kit/format-time";
import { TONE_CLASS, type Tone } from "@/components/kit/tone";
import { Button } from "@/components/ui/button";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import { Spinner } from "@/components/ui/spinner";

import { RUN_STATE_TONES } from "./collector-state";
import { STREAM_STATUS_META, diagnoseStreamHealth } from "./stream-shared";

const STREAM_KEY = "stream.collection";

// The tick itself runs no faster than 30s (the setting's floor), so polling the
// panel harder than that only re-renders the same numbers. Matches the
// rank/subscription dashboards in kind, not in value: their sweeps are minutes
// apart, this one is seconds.
const REFETCH_MS = 30_000;

export function StreamHealthDashboard() {
  const queryClient = useQueryClient();
  const { user } = useAuthProfile();
  const isSuperuser = user?.isSuperuser ?? false;

  // No workspace in the key: one poller, one Redis key, one set of numbers.
  const healthQuery = useQuery({
    queryKey: ["admin", "streams", "health"],
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
      notify.success(health?.enabled ? "Polling paused" : "Polling resumed");
      queryClient.invalidateQueries({ queryKey: ["admin", "streams"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "settings"] });
    },
    onError: (error) =>
      notify.apiError(error, { title: "Could not change the polling state — try again" })
  });

  if (healthQuery.isLoading || !health) {
    return <StatTileGridSkeleton />;
  }

  const diagnosis = diagnoseStreamHealth(health);
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
            labels={{ running: "Polling", paused: "Paused" }}
            fallback="Paused"
            dot
          />
          <span className="text-muted-foreground">
            every <span className="tabular-nums">{formatInterval(health.interval_seconds)}</span> ·{" "}
            <span className="tabular-nums">{health.batch_size}</span>/batch
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
            {health.enabled ? "Pause polling" : "Resume polling"}
          </Button>
        )}
      </div>

      <div className={cn("space-y-1 rounded-xl border p-4 text-sm", TONE_CLASS[diagnosis.tone])}>
        <p className="flex items-center gap-2 font-medium">
          {diagnosis.tone === "danger" || diagnosis.tone === "warning" ? (
            <AlertTriangle aria-hidden className="h-4 w-4 shrink-0" />
          ) : null}
          {diagnosis.label}
        </p>
        {diagnosis.hint ? (
          <p className="text-muted-foreground">{diagnosis.hint}</p>
        ) : (
          <p className="text-muted-foreground">
            Last tick {formatRelative(health.last_run_at)}. Nothing to do.
          </p>
        )}
      </div>

      <StatTileGrid>
        <StatTile
          label="Last tick"
          value={formatRelative(health.last_run_at)}
          detail={
            health.status === null
              ? "Never run — no outcome recorded yet"
              : STREAM_STATUS_META[health.status].label
          }
          icon={Clock}
          tone={diagnosis.tone}
        />

        <StatTile
          label="Tournaments"
          value={health.tournaments_active ?? "—"}
          detail={`${health.tournaments_updated ?? 0} changed state on the last tick`}
          icon={Trophy}
        />

        <StatTile
          label="Channels polled"
          value={health.channels_polled ?? "—"}
          detail="Twitch channels asked about on the last tick"
          icon={Radio}
        />

        <StatTile
          label="Live now"
          value={health.live_channels ?? "—"}
          detail="Channels Twitch reported as streaming"
          icon={Radio}
          tone={(health.live_channels ?? 0) > 0 ? "success" : "neutral"}
        />

        <StatTile
          label="Rate limit left"
          value={remaining ?? "—"}
          detail="Of an 800/min Helix bucket shared with sign-ins"
          icon={Gauge}
          tone={rateTone}
        />
      </StatTileGrid>
    </div>
  );
}
