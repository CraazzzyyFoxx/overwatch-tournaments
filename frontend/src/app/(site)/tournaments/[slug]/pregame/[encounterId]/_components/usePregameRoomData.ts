"use client";

import { useMemo } from "react";
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

  const mapQuery = useQuery({
    queryKey: mapKey,
    queryFn: () => pickBanService.getPickBanState("map", encounterId),
    enabled,
    refetchInterval: (query) =>
      query.state.data?.session != null && !query.state.data.is_complete ? 4000 : false
  });
  const heroQuery = useQuery({
    queryKey: heroKey,
    queryFn: () => pickBanService.getPickBanState("hero", encounterId),
    enabled,
    refetchInterval: (query) =>
      query.state.data?.session != null && !query.state.data.is_complete ? 4000 : false
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

  // The hub only delivers a thin "changed" signal on every mutation — the
  // authoritative state is always refetched. Map keeps the legacy topic name
  // (`encounter:{id}:map-veto`); hero uses the generic kind-suffixed one.
  // Either signal refetches BOTH: the two sessions are two phases of one loop,
  // so a map pick opens a hero round and a confirmed result opens a map round
  // — the state that changed is rarely only the one that was acted on.
  // The series score lives on the ENCOUNTER (`map_report.submit_map_report`
  // increments it), so a confirmed map moves a number this room renders from a
  // third query -- refetch it here too, or the captain who reported FIRST kept
  // reading a stale scoreboard until they reloaded.
  const invalidateRoom = () => {
    void queryClient.invalidateQueries({ queryKey: mapKey });
    void queryClient.invalidateQueries({ queryKey: heroKey });
    void queryClient.invalidateQueries({ queryKey: encounterQueryKeys.detail(encounterId) });
  };
  useRealtimeTopic(`encounter:${encounterId}:map-veto`, invalidateRoom);
  useRealtimeTopic(`encounter:${encounterId}:pick-ban:hero`, invalidateRoom);

  const readyMutation = useMutation({
    mutationFn: () => pickBanService.markReady(encounterId),
    onError: (error) => notify.apiError(error, { title: t("ready.failed") }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: mapKey });
      void queryClient.invalidateQueries({ queryKey: heroKey });
    }
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
