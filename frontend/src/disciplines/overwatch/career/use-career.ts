"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useCatalogEntities } from "@/hooks/useCatalogEntities";
import { userQueryKeys } from "@/lib/users/query-keys";
import rankService from "@/services/rank.service";
import userService from "@/services/user.service";

const STALE_MS = 5 * 60 * 1000;

/** A player's collected career; the server refreshes it every ~2 h, so five minutes of client cache is plenty. */
export function useCareer(userId: number, discipline: string) {
  return useQuery({
    queryKey: userQueryKeys.career(userId, discipline),
    queryFn: ({ signal }) => userService.getUserCareer(userId, discipline, { signal }),
    staleTime: STALE_MS
  });
}

/** The player's current ranks — the read the rank history already uses, so its cache is shared. */
export function useCurrentRanks(userId: number, discipline: string) {
  return useQuery({
    queryKey: userQueryKeys.rankCurrent(userId, discipline),
    queryFn: () => rankService.getUserCurrentRanks(userId, discipline),
    staleTime: STALE_MS
  });
}

/** What a portrait needs of a hero key (the career's `character` is the catalog slug). */
interface HeroFace {
  name: string;
  image_path: string | null;
}

/** Hero key → catalog face; a key the catalog does not know draws its key on a neutral tile. */
export function useHeroFaces(discipline: string): (key: string) => HeroFace {
  const { data } = useCatalogEntities(discipline, "character");
  const bySlug = useMemo(() => new Map((data ?? []).map((entity) => [entity.slug, entity])), [data]);
  return (key) => bySlug.get(key) ?? { name: key, image_path: null };
}
