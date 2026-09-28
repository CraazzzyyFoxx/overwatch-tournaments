"use client";

import { useQuery } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import pickBanService from "@/services/pickBan.service";
import type { PickBanRulesCatalog } from "@/types/tournament.types";

/**
 * The engine's leaf/constraint specs, group vocabularies and presets (§10).
 *
 * One registry for the whole session: it only changes when the engine ships a
 * new leaf, so the constructor never refetches it per mount — the same deal the
 * achievement editor strikes with `condition-types`.
 */
export function useRulesCatalog() {
  return useQuery<PickBanRulesCatalog>({
    queryKey: tournamentQueryKeys.pickBanRulesCatalog(),
    queryFn: () => pickBanService.getRulesCatalog(),
    staleTime: Infinity,
  });
}
