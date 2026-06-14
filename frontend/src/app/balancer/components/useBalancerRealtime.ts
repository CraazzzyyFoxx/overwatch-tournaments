"use client";

import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import { realtimeClient } from "@/services/realtime.service";
import balancerService from "@/services/balancer.service";
import { useRealtimeStore } from "@/stores/realtime.store";
import { notify } from "@/lib/notify";
import type { RealtimeEventEnvelope } from "@/types/realtime.types";

import type { JobAction } from "./useBalancerJob";
import { appendGeneratedVariants, type JobResultContext } from "./balancer-job-result";
import type { BalanceVariant } from "./workspace-helpers";

/**
 * Tournament-scoped balancer topic. Matches `realtime_topics.balancer` on the
 * backend; access is gated by workspace membership in the realtime-service ACL.
 */
export function balancerRealtimeTopic(tournamentId: number | null): string | null {
  return tournamentId != null ? `tournament:${tournamentId}:balancer` : null;
}

// Event-type literals mirror shared/services/balancer_realtime.py.
const PRESENCE_EVENT = "balancer.presence";
const JOB_EVENT_PREFIX = "balancer_job.";
const DATA_EVENT_PREFIX = "balancer.";

type BalancerJobEventData = {
  tournament_id?: number;
  job_id: string;
  status: string;
  progress?: { percent?: number | null; current?: number | null; total?: number | null } | null;
  error?: string | null;
};

type PresenceEventData = {
  user_ids?: number[];
};

type UseBalancerRealtimeOptions = {
  tournamentId: number | null;
  dispatchJob: React.Dispatch<JobAction>;
  setVariants: React.Dispatch<React.SetStateAction<BalanceVariant[]>>;
  setActiveVariantId: React.Dispatch<React.SetStateAction<string | null>>;
  setPresence: (userIds: number[]) => void;
};

function extractPercent(progress: BalancerJobEventData["progress"]): number | null {
  if (!progress) {
    return null;
  }
  if (typeof progress.percent === "number") {
    return progress.percent;
  }
  const { current, total } = progress;
  if (typeof current === "number" && typeof total === "number" && total > 0) {
    return (current / total) * 100;
  }
  return null;
}

export function useBalancerRealtime({
  tournamentId,
  dispatchJob,
  setVariants,
  setActiveVariantId,
  setPresence
}: UseBalancerRealtimeOptions): {
  registerLocalJob: (jobId: string, context: JobResultContext) => void;
} {
  const queryClient = useQueryClient();
  const topic = balancerRealtimeTopic(tournamentId);
  const connectionState = useRealtimeStore((state) => state.connectionState);

  // Run-local context (skipped/config) keyed by job id, so the shared succeeded
  // handler can label variants exactly as the initiator's run intended.
  const jobContextRef = useRef<Map<string, JobResultContext>>(new Map());
  // Guard against applying the same job result twice (e.g. live event + replay).
  const appliedJobsRef = useRef<Set<string>>(new Set());

  const registerLocalJob = useCallback((jobId: string, context: JobResultContext) => {
    jobContextRef.current.set(jobId, context);
  }, []);

  const invalidateForDataEvent = useCallback(
    (eventType: string) => {
      if (tournamentId == null) {
        return;
      }
      const keys: unknown[][] = [];
      switch (eventType) {
        case "balancer.registrations_changed":
          keys.push(["balancer-admin", "registrations", tournamentId]);
          break;
        case "balancer.balance_saved":
        case "balancer.teams_changed":
          keys.push(["balancer-public", "balance", tournamentId]);
          break;
        case "balancer.config_changed":
          keys.push(["balancer-admin", "tournament-config", tournamentId]);
          break;
        default:
          return;
      }
      for (const queryKey of keys) {
        void queryClient.invalidateQueries({ queryKey });
      }
    },
    [queryClient, tournamentId]
  );

  const handleJobSucceeded = useCallback(
    async (jobId: string) => {
      if (appliedJobsRef.current.has(jobId)) {
        return;
      }
      appliedJobsRef.current.add(jobId);
      dispatchJob({ type: "update", status: "succeeded", message: "Balance completed", progress: 100 });
      try {
        const result = await balancerService.getBalanceJobResult(jobId);
        const context = jobContextRef.current.get(jobId) ?? {};
        appendGeneratedVariants(setVariants, setActiveVariantId, result, context);
        jobContextRef.current.delete(jobId);
        dispatchJob({ type: "clear" });
        notify.success("Balance completed");
      } catch (error) {
        const message = error instanceof Error ? error.message : "Failed to fetch balance result";
        dispatchJob({ type: "update", status: "failed", message, progress: null });
        notify.error("Balance failed", { description: message });
      }
    },
    [dispatchJob, setActiveVariantId, setVariants]
  );

  const handleJobEvent = useCallback(
    (eventType: string, data: BalancerJobEventData) => {
      const percent = extractPercent(data.progress);
      switch (eventType) {
        case "balancer_job.queued":
          dispatchJob({ type: "update", status: "queued", message: "Job queued", progress: 0 });
          return;
        case "balancer_job.running":
        case "balancer_job.progress":
          dispatchJob({
            type: "update",
            status: "running",
            message: "Balancing teams…",
            progress: percent
          });
          return;
        case "balancer_job.succeeded":
          void handleJobSucceeded(data.job_id);
          return;
        case "balancer_job.failed": {
          const message = data.error ?? "Balance failed";
          dispatchJob({ type: "update", status: "failed", message, progress: null });
          notify.error("Balance failed", { description: message });
          return;
        }
        default:
          return;
      }
    },
    [dispatchJob, handleJobSucceeded]
  );

  const handleEvent = useCallback(
    (event: RealtimeEventEnvelope) => {
      const { event_type: eventType, data } = event;
      if (eventType === PRESENCE_EVENT) {
        setPresence((data as PresenceEventData).user_ids ?? []);
        return;
      }
      if (eventType.startsWith(JOB_EVENT_PREFIX)) {
        handleJobEvent(eventType, data as BalancerJobEventData);
        return;
      }
      if (eventType.startsWith(DATA_EVENT_PREFIX)) {
        invalidateForDataEvent(eventType);
      }
    },
    [handleJobEvent, invalidateForDataEvent, setPresence]
  );

  useRealtimeTopic(topic, handleEvent);

  // Reset presence and the applied-job guard when switching tournaments; the new
  // topic re-emits a fresh presence frame on subscribe.
  useEffect(() => {
    setPresence([]);
    appliedJobsRef.current.clear();
    jobContextRef.current.clear();
  }, [tournamentId, setPresence]);

  // Belt-and-suspenders: cursor replay already catches up data events on
  // reconnect, but a replay-gap could drop them, so refetch the core queries
  // whenever the socket comes back after a drop.
  const previousConnectionRef = useRef(connectionState);
  useEffect(() => {
    const previous = previousConnectionRef.current;
    previousConnectionRef.current = connectionState;
    if (previous === "reconnecting" && connectionState === "connected" && tournamentId != null) {
      void queryClient.invalidateQueries({
        queryKey: ["balancer-admin", "registrations", tournamentId]
      });
      void queryClient.invalidateQueries({
        queryKey: ["balancer-public", "balance", tournamentId]
      });
      // Re-seed catch-up replay from the latest cursor for this topic.
      if (topic) {
        realtimeClient.resubscribe(topic);
      }
    }
  }, [connectionState, queryClient, tournamentId, topic]);

  return { registerLocalJob };
}
