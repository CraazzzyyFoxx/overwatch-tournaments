"use client";

import { useQuery } from "@tanstack/react-query";

import adminService from "@/services/admin.service";
import tournamentService from "@/services/tournament.service";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

/**
 * What the achievements screen reads but does not page: the tournament list
 * behind the comboboxes, the manual overrides, and the full rule catalog the
 * evaluate/override pickers need.
 *
 * The catalog is deliberately lazy — it is a `per_page: -1` request, so it is
 * not worth fetching until something on screen actually reads every rule.
 */
export function useAchievementCatalog({
  workspaceId,
  pickersOpen,
}: {
  workspaceId: number | null;
  /** An open evaluate/override dialog needs every rule, not just the current page. */
  pickersOpen: boolean;
}) {
  const { data: tournaments } = useQuery({
    queryKey: tournamentQueryKeys.list(),
    queryFn: () => tournamentService.getAll(null),
  });

  const { data: overrides, refetch: refetchOverrides } = useQuery({
    queryKey: achievementQueryKeys.overridesAll(workspaceId),
    queryFn: () => adminService.getAchievementOverrides(workspaceId!),
    enabled: !!workspaceId,
  });

  // The overrides table resolves rule ids to slugs, so a workspace with
  // overrides needs the catalog even before a dialog opens.
  const { data: allRulesPage } = useQuery({
    queryKey: [...achievementQueryKeys.adminList(workspaceId), "catalog"],
    queryFn: () => adminService.getAchievementRules(workspaceId!, { per_page: -1 }),
    enabled: !!workspaceId && (pickersOpen || Boolean(overrides?.length)),
  });

  return {
    tournaments,
    overrides,
    refetchOverrides,
    allRules: allRulesPage?.results,
  };
}
