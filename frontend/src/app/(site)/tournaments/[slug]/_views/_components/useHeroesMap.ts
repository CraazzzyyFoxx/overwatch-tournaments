"use client";

import { useMemo } from "react";

import { useHeroesCatalog } from "@/hooks/useHeroesCatalog";
import type { Hero } from "@/types/hero.types";

/**
 * The hero catalogue as a slug lookup, built once per catalogue rather than
 * once per row. `enabled: false` keeps the request unsent until something on
 * screen actually needs a hero portrait.
 */
export function useHeroesMap({ enabled = true }: { enabled?: boolean } = {}): Map<string, Hero> {
  const { data: heroesData } = useHeroesCatalog({ enabled });

  return useMemo(() => {
    const map = new Map<string, Hero>();
    if (heroesData) {
      for (const h of heroesData) {
        map.set(h.slug, h);
      }
    }
    return map;
  }, [heroesData]);
}
