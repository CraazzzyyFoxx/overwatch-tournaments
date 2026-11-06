"use client";

import { useQuery } from "@tanstack/react-query";

import adminService from "@/services/admin.service";
import tournamentService from "@/services/tournament.service";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import { ALL_DISCIPLINES } from "@/lib/site/discipline-scope";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

/**
 * What the achievements screen reads but does not page: the tournament list
 * behind the evaluate picker, the manual overrides, and the full rule catalog
 * the evaluate picker and the overrides table need.
 *
 * The catalog is deliberately lazy — it is a `per_page: -1` request, so it is
 * not worth fetching until something on screen actually reads every rule.
 */
export function useAchievementCatalog({
  workspaceId,
  discipline,
  pickersOpen,
}: {
  workspaceId: number | null;
  /** The selected game: its overrides and rules, never another game's. `null` when none is enabled. */
  discipline: string | null;
  /** An open evaluate dialog needs every rule, not just the current page. */
  pickersOpen: boolean;
}) {
  // The workspace's tournaments: nothing is read until the workspace is known.
  const { data: tournaments } = useQuery({
    queryKey: tournamentQueryKeys.adminList(workspaceId, ALL_DISCIPLINES),
    queryFn: () => tournamentService.getAll(workspaceId),
    enabled: workspaceId !== null,
  });

  const { data: overrides } = useQuery({
    queryKey: achievementQueryKeys.overridesAll(workspaceId, discipline),
    queryFn: () => adminService.getAchievementOverrides(workspaceId!, discipline!),
    enabled: !!workspaceId && !!discipline,
  });

  // The overrides table resolves rule ids to slugs, so a workspace with
  // overrides needs the catalog even before a dialog opens.
  const { data: allRulesPage } = useQuery({
    queryKey: [...achievementQueryKeys.adminList(workspaceId, discipline), "catalog"],
    queryFn: () => adminService.getAchievementRules(workspaceId!, discipline!, { per_page: -1 }),
    enabled: !!workspaceId && !!discipline && (pickersOpen || Boolean(overrides?.length)),
  });

  return {
    tournaments,
    overrides,
    allRules: allRulesPage?.results,
  };
}
