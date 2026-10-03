"use client";

import { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import captainService from "@/services/captain.service";
import encounterService from "@/services/encounter.service";
import pickBanService from "@/services/pickBan.service";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { notify } from "@/lib/notify";
import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import { useHeroesCatalog } from "@/hooks/useHeroesCatalog";
import { useMapsCatalog } from "@/hooks/useMapsCatalog";
import { createTrailingCoalescer, type Coalescer } from "@/lib/realtime/coalesce";
import { useRealtimeStore } from "@/stores/realtime.store";
import type { PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import type { PickBanSide } from "@/components/pick-ban/pick-ban-model";
import type { Encounter } from "@/types/encounter.types";
import type { MapRead } from "@/types/map.types";
import type { PickBanKind, PickBanState } from "@/types/tournament.types";

export interface PregameRoomData {
  /** Query keys the room's own writes invalidate, handed to child controls. */
  mapKey: unknown[];
  heroKey: unknown[];
  isPending: boolean;
  isError: boolean;
  encounter: Encounter | null;
  mapState: PickBanState | null;
  heroState: PickBanState | null;
  mapsById: Record<number, PickBanItemLike | undefined>;
  heroesById: Record<number, PickBanItemLike | undefined>;
  itemsByKind: Record<PickBanKind, Record<number, PickBanItemLike | undefined>>;
  /** Every map in the catalog, for the no-veto "which map did you play" picker. */
  mapChoices: MapRead[];
  viewerSide: PickBanSide | null;
  readyPending: boolean;
  markReady: () => void;
  refetchAll: () => void;
  /** Refetch both sessions and the encounter after any local mutation. */
  invalidateRoom: () => void;
}

const POLL_MS = 4000;
const POLL_JITTER_MS = 2500;
const PAUSED_FALLBACK_MS = 30_000;

function roomSnapshot(map?: PickBanState | null, hero?: PickBanState | null) {
  const states = [map, hero];
  return {
    structure: JSON.stringify([
      map?.games,
      map?.series,
      ...states.map((state) => [
        state?.session?.id,
        state?.session?.status,
        state?.session?.paused_at
      ])
    ]),
    progress: JSON.stringify(states.map((state) => [
      state?.session?.id, state?.current_step_index, state?.current_round, state?.is_complete
    ]))
  };
}

/**
 * Every read the duel pre-game room renders from, plus the realtime wiring
 * that keeps them honest.
 *
 * Turn timeouts auto-resolve lazily server-side, the next time anyone reads
 * this session's state (backend: `pick_ban_action.auto_resolve_timeout`) --
 * there's no push event for time simply elapsing on its own, so an active,
 * unresolved session polls itself close to real time instead of waiting for
 * the next manual action or page load to notice the clock ran out.
 */
export function usePregameRoomData(encounterId: number): PregameRoomData {
  const t = useTranslations("pickBan.room");
  const queryClient = useQueryClient();
  const enabled = Number.isFinite(encounterId) && encounterId > 0;
  const mapKey = ["pregame-state", encounterId, "map"];
  const heroKey = ["pregame-state", encounterId, "hero"];
  const mapTopic = `encounter:${encounterId}:map-veto`;
  const heroTopic = `encounter:${encounterId}:pick-ban:hero`;
  const realtimeReady = useRealtimeStore((state) =>
    state.connectionState === "connected" && !state.topicErrors[mapTopic] && !state.topicErrors[heroTopic]
  );
  const [polling] = useState(() => ({
    map: POLL_MS + Math.floor(Math.random() * POLL_JITTER_MS),
    hero: POLL_MS + Math.floor(Math.random() * POLL_JITTER_MS)
  }));
  const refetchInterval = (state: PickBanState | null | undefined, interval: number) => {
    if (state?.session == null || state.is_complete) return false;
    if (state.session.paused_at != null) {
      return realtimeReady ? false : PAUSED_FALLBACK_MS + interval - POLL_MS;
    }
    return interval;
  };

  const mapQuery = useQuery({
    queryKey: mapKey,
    queryFn: () => pickBanService.getPickBanState("map", encounterId),
    enabled,
    refetchInterval: (query) => refetchInterval(query.state.data, polling.map)
  });
  const heroQuery = useQuery({
    queryKey: heroKey,
    queryFn: () => pickBanService.getPickBanState("hero", encounterId),
    enabled,
    refetchInterval: (query) => refetchInterval(query.state.data, polling.hero)
  });
  const encounterQuery = useQuery({
    queryKey: encounterQueryKeys.detail(encounterId),
    queryFn: () => encounterService.getEncounter(encounterId),
    enabled
  });
  const mapsQuery = useMapsCatalog();
  const heroesQuery = useHeroesCatalog();
  // `build_unavailable_state` reports `viewer_side: null` regardless of
  // identity (there is no session yet to resolve a side against), so the
  // readiness gate's "you're a captain" check needs its own read.
  const roleQuery = useQuery({
    queryKey: encounterQueryKeys.myRole(encounterId),
    queryFn: () => captainService.getMyRole(encounterId),
    enabled,
    retry: false
  });

  // Both topics and local writes share one bounded, jittered batch. Never
  // restart its timer on another signal: continuous blind drafts must not
  // postpone a locked submission or resume indefinitely.
  const batch = useRef({ states: false, details: false, scheduled: false });
  const coalescer = useRef<Coalescer | null>(null);
  const observed = useRef<ReturnType<typeof roomSnapshot> | null>(null);
  const schedule = useCallback((states: boolean, details = false) => {
    batch.current.states ||= states;
    batch.current.details ||= details;
    if (!batch.current.scheduled) {
      batch.current.scheduled = true;
      coalescer.current?.schedule();
    }
  }, []);
  const flushRoom = useEffectEvent(async (isCurrent: () => boolean) => {
    const refreshStates = batch.current.states;
    batch.current.states = false;
    if (refreshStates) {
      // Await both phases before deciding whether this changed games/results
      // or a session control. Picks/drafts alone do not reread the encounter.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: mapKey }),
        queryClient.invalidateQueries({ queryKey: heroKey })
      ]);
    }
    if (!isCurrent()) return;
    const next = roomSnapshot(
      queryClient.getQueryData<PickBanState>(mapKey),
      queryClient.getQueryData<PickBanState>(heroKey)
    );
    if (observed.current && observed.current.structure !== next.structure) {
      batch.current.details = true;
    }
    observed.current = next;
    if (batch.current.details) {
      batch.current.details = false;
      void queryClient.invalidateQueries({ queryKey: encounterQueryKeys.detail(encounterId) });
      for (const match of encounterQuery.data?.matches ?? []) {
        void queryClient.invalidateQueries({ queryKey: encounterQueryKeys.matchDetail(match.id) });
      }
    }
    if (refreshStates) {
      void queryClient.invalidateQueries({ queryKey: encounterQueryKeys.roomHistory(encounterId) });
    }
    batch.current.scheduled = false;
    if (batch.current.states || batch.current.details) schedule(false);
  });
  useEffect(() => {
    let current = true;
    const timer = createTrailingCoalescer(
      () => { void flushRoom(() => current); },
      250 + Math.floor(Math.random() * 500)
    );
    coalescer.current = timer;
    return () => {
      current = false;
      timer.cancel();
      coalescer.current = null;
      batch.current = { states: false, details: false, scheduled: false };
      observed.current = null;
    };
  }, [encounterId]);

  useEffect(() => {
    if (!mapQuery.data || !heroQuery.data) return;
    const next = roomSnapshot(mapQuery.data, heroQuery.data);
    const previous = observed.current;
    observed.current = next;
    if (!previous) return;
    // Poll-driven timeout settlement must also wake the OTHER phase, even
    // when its session did not exist yet and the websocket signal was missed.
    const progressChanged = previous.progress !== next.progress && !batch.current.scheduled;
    const structureChanged = previous.structure !== next.structure;
    if (progressChanged || structureChanged) schedule(progressChanged, structureChanged);
  }, [mapQuery.data, heroQuery.data, schedule]);

  const invalidateRoom = () => schedule(true, true);
  const invalidateStates = () => schedule(true);
  useRealtimeTopic(mapTopic, invalidateStates, [], invalidateRoom);
  useRealtimeTopic(heroTopic, invalidateStates, [], invalidateRoom);

  // Parsed logs add/replace matches without moving the game's accepted score.
  // The parser names affected encounters on the tournament invalidation, so
  // only this room's explicit encounter changes join the full-refresh batch.
  const tournamentId = encounterQuery.data?.tournament_id;
  useRealtimeTopic<{
    resources?: string[];
    entity_ids?: { encounter_ids?: number[] };
  }>(
    tournamentId != null ? `tournament:${tournamentId}:invalidation` : null,
    (event) => {
      const resources = event.data?.resources;
      const ids = event.data?.entity_ids?.encounter_ids;
      if (Array.isArray(resources) && resources.includes("tournament.encounters") &&
          Array.isArray(ids) && ids.includes(encounterId)) {
        invalidateRoom();
      }
    }
  );

  const readyMutation = useMutation({
    mutationFn: () => pickBanService.markReady(encounterId),
    onError: (error) => notify.apiError(error, { title: t("ready.failed") }),
    onSettled: invalidateStates
  });

  const mapsById = useMemo(() => {
    const byId: Record<number, PickBanItemLike | undefined> = {};
    for (const map of mapsQuery.data ?? []) byId[map.id] = map;
    return byId;
  }, [mapsQuery.data]);
  const heroesById = useMemo(() => {
    const byId: Record<number, PickBanItemLike | undefined> = {};
    for (const hero of heroesQuery.data ?? []) byId[hero.id] = hero;
    return byId;
  }, [heroesQuery.data]);

  const encounter = encounterQuery.data ?? null;
  const mapState = mapQuery.data ?? null;
  const heroState = heroQuery.data ?? null;

  return {
    mapKey,
    heroKey,
    isPending: mapQuery.isPending || heroQuery.isPending || encounterQuery.isPending,
    isError:
      mapQuery.isError ||
      heroQuery.isError ||
      encounter === null ||
      mapState === null ||
      heroState === null,
    encounter,
    mapState,
    heroState,
    mapsById,
    heroesById,
    itemsByKind: { map: mapsById, hero: heroesById },
    mapChoices: mapsQuery.data ?? [],
    viewerSide: roleQuery.data?.side ?? null,
    readyPending: readyMutation.isPending,
    markReady: () => readyMutation.mutate(),
    refetchAll: () => {
      void mapQuery.refetch();
      void heroQuery.refetch();
      void encounterQuery.refetch();
    },
    invalidateRoom
  };
}
