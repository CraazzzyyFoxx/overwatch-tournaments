"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { UNKNOWN_ROUND_SHAPE } from "@/lib/bracket-round-name";
import mapService from "@/services/map.service";
import pickBanService from "@/services/pickBan.service";
import tournamentService from "@/services/tournament.service";
import type { MapRead } from "@/types/map.types";
import type { PickBanConfig } from "@/types/tournament.types";

export type MapPoolGroup = {
  /** Game mode name (Control, Hybrid…); "—" when the catalogue names none. */
  gamemode: string;
  maps: MapRead[];
};

export type MapPoolView = {
  byGamemode: MapPoolGroup[];
  total: number;
};

/** One slot of a slot-mode config: the candidates for map N of the series. */
export type MapPoolSlotView = {
  position: number;
  maps: MapRead[];
};

/**
 * One scope a veto config is saved at: the tournament, a stage, or — the case
 * organizers actually author — a single round of a stage.
 */
export type MapPoolScopeView = {
  /** `stage:<id>` / `round:<stageId>:<round>`, the admin scope vocabulary. */
  key: string;
  stageId: number;
  stageName: string;
  /** "Round 2" / "LB Round 1"; `null` for a config that covers the whole stage. */
  round: string | null;
  /** The scope in one line — "Playoff · LB Round 1" — for labels and titles. */
  title: string;
  pool: MapPoolView;
  /**
   * Slot mode picks one map per series slot from its own candidate list, so a
   * round's pool is a list of lists, not one bag of maps. `null` for a flat
   * pool-mode config, where every map is a candidate for every map of the series.
   */
  slots: MapPoolSlotView[] | null;
};

/** A stage's own pool: the union of its rounds, and those rounds in play order. */
export type MapPoolStageView = {
  stageId: number;
  stageName: string;
  pool: MapPoolView;
  rounds: MapPoolScopeView[];
};

export type TournamentMapPool = {
  /** Every map any veto config of the tournament names, grouped by game mode. */
  pool: MapPoolView;
  /**
   * The pools the organizer actually authored, grouped by stage and in play
   * order within it. Empty when a single tournament-wide config decides
   * everything and `pool` is already the whole story.
   */
  stages: MapPoolStageView[];
  isPending: boolean;
  isError: boolean;
  isFetching: boolean;
  refetch: () => void;
};

export const mapPoolQueryKeys = {
  configs: (tournamentId: number) =>
    ["public", "tournament", tournamentId, "pick-ban-configs"] as const,
  maps: ["maps", "all", "gamemode"] as const,
  stages: (tournamentId: number) => ["public", "tournament", tournamentId, "stages"] as const
};

/** Every map id the given veto configs name, anywhere: pool, slots, reserves. */
export function collectPoolIds(configs: PickBanConfig[]): Set<number> {
  const ids = new Set<number>();
  for (const config of configs) {
    for (const id of config.item_ids) ids.add(id);
    for (const slot of config.slots) {
      for (const id of slot.candidates) ids.add(id);
      if (slot.reserve_item_id != null) ids.add(slot.reserve_item_id);
    }
  }
  return ids;
}

export function groupByGamemode(maps: MapRead[]): MapPoolView {
  const buckets = new Map<string, MapRead[]>();
  for (const map of maps) {
    const key = map.gamemode?.name ?? "—";
    const bucket = buckets.get(key);
    if (bucket) bucket.push(map);
    else buckets.set(key, [map]);
  }
  const byGamemode = [...buckets.entries()]
    .map(([gamemode, list]) => ({
      gamemode,
      maps: [...list].sort((a, b) => a.name.localeCompare(b.name))
    }))
    .sort((a, b) => a.gamemode.localeCompare(b.gamemode));
  return { byGamemode, total: maps.length };
}

/**
 * Sort weight of a round inside its stage: the stage-wide pool first, then the
 * upper bracket climbing (1, 2, 3…), then the lower bracket (-1, -2…) — the
 * order the bracket itself reads in.
 */
function roundOrder(round: number | null): number {
  if (round == null) return 0;
  return round > 0 ? round : 500 - round;
}

/**
 * The tournament's map pool, derived from its pick-ban configs.
 *
 * There is no "map pool" entity: the pool is whatever the veto configuration
 * can produce. `pool` is the union across every config — the whole tournament's
 * map list. `scopes` keeps the shape the organizer authored: pools are usually
 * saved per ROUND (a Bo3 round names three slot pools of its own), and merging
 * those into one bag hides which maps a given round can actually play.
 */
export function useTournamentMapPool(tournamentId: number): TournamentMapPool {
  const roundLabel = useBracketRoundLabel();
  // No `.catch(() => ({ configs: [] }))` here: a failed read must stay
  // distinguishable from "the organizer configured nothing".
  const configsQuery = useQuery({
    queryKey: mapPoolQueryKeys.configs(tournamentId),
    queryFn: () => pickBanService.listPublicConfigs(tournamentId)
  });
  // `entities: ["gamemode"]` is load-bearing: the maps endpoint only serialises
  // the gamemode relation when asked, and the pool is grouped by it.
  const mapsQuery = useQuery({
    queryKey: mapPoolQueryKeys.maps,
    queryFn: () =>
      mapService.getAll({ perPage: -1, sort: "name", order: "asc", entities: ["gamemode"] })
  });
  const stagesQuery = useQuery({
    queryKey: mapPoolQueryKeys.stages(tournamentId),
    queryFn: () => tournamentService.getStages(tournamentId)
  });

  const derived = useMemo(() => {
    const configs = (configsQuery.data?.configs ?? []).filter((config) => config.kind === "map");
    const maps = (mapsQuery.data?.results ?? []).filter((map) => map.in_competitive !== false);
    const mapsById = new Map(maps.map((map) => [map.id, map]));
    const resolve = (ids: Iterable<number>) =>
      [...ids].map((id) => mapsById.get(id)).filter((map): map is MapRead => map !== undefined);

    const pool = groupByGamemode(resolve(collectPoolIds(configs)));

    const stagesById = new Map((stagesQuery.data ?? []).map((stage) => [stage.id, stage] as const));
    const scopes: MapPoolScopeView[] = configs
      .filter((config) => config.stage_id != null)
      .map((config) => {
        const stageId = config.stage_id as number;
        const stage = stagesById.get(stageId);
        const stageName = stage?.name ?? `#${stageId}`;
        const slots = [...config.slots]
          .sort((left, right) => left.position - right.position)
          .map((slot) => ({
            position: slot.position,
            maps: resolve(
              new Set(
                slot.reserve_item_id == null
                  ? slot.candidates
                  : [...slot.candidates, slot.reserve_item_id]
              )
            )
          }));
        // No encounters are read here, so the stage's shape is unknown: a round
        // keeps its plain depth rather than being guessed into a final.
        const round =
          config.round == null ? null : roundLabel(config.round, UNKNOWN_ROUND_SHAPE);
        return {
          key: config.round == null ? `stage:${stageId}` : `round:${stageId}:${config.round}`,
          stageId,
          stageName,
          round,
          title: round == null ? stageName : `${stageName} · ${round}`,
          pool: groupByGamemode(resolve(collectPoolIds([config]))),
          slots: slots.length > 0 ? slots : null,
          order: (stage?.order ?? stageId) * 1000 + roundOrder(config.round)
        };
      })
      .sort((left, right) => left.order - right.order);

    // Consecutive runs are one stage, since the sort put them in play order.
    // A stage's pool is the union of its rounds — what "this stage can play".
    const stages: MapPoolStageView[] = [];
    for (const scope of scopes) {
      const last = stages.at(-1);
      if (last?.stageId === scope.stageId) last.rounds.push(scope);
      else
        stages.push({
          stageId: scope.stageId,
          stageName: scope.stageName,
          pool: { byGamemode: [], total: 0 },
          rounds: [scope]
        });
    }
    for (const stage of stages) {
      const ids = new Set<number>();
      for (const round of stage.rounds) {
        for (const group of round.pool.byGamemode) for (const map of group.maps) ids.add(map.id);
      }
      stage.pool = groupByGamemode(resolve(ids));
    }

    return { pool, stages };
  }, [configsQuery.data, mapsQuery.data, stagesQuery.data, roundLabel]);

  return {
    ...derived,
    isPending: configsQuery.isPending || mapsQuery.isPending,
    isError: configsQuery.isError || mapsQuery.isError,
    isFetching: configsQuery.isFetching || mapsQuery.isFetching,
    refetch: () => {
      void configsQuery.refetch();
      void mapsQuery.refetch();
    }
  };
}
