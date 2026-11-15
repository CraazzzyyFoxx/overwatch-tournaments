"use client";

// The one subscription rule every tournament in the workspace enforces. It used
// to live in the per-tournament registration form builder, which re-asked the
// same question for every new tournament, and then briefly in the collector
// dashboard, where it read as monitoring rather than configuration — which it is.

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import SubscriptionRequirementEditor from "@/components/admin/subscriptions/SubscriptionRequirementEditor";
import { SettingGroup } from "@/components/kit/SettingRow";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import balancerAdminService from "@/services/balancer-admin.service";
import type { SubscriptionRequirement } from "@/types/registration.types";
import { workspaceQueryKeys } from "@/lib/workspace/query-keys";

const EMPTY_REQUIREMENT: SubscriptionRequirement = { mode: "all", requirements: [] };

/** A deliberately STRICTER approximation of server equality: mode plus the sorted
 *  provider/threshold set. Order is not part of the rule (`parse_requirement` dedupes
 *  into a dict and the Kleene composition is commutative), so reordering the editor's
 *  rows must not read as a policy change.
 *
 *  It does NOT reproduce the rest of `parse_requirement` -- dedupe-by-provider keeping
 *  the strictest threshold, clamping `min_tier_rank` to at least 1, coercing a non-int
 *  rank, dropping a blank provider -- so it can report a change the server would
 *  collapse to nothing. Every divergence over-warns, never under-warns, which is the
 *  safe direction for a warning about admission. */
function sameRule(a: SubscriptionRequirement, b: SubscriptionRequirement): boolean {
  if ((a.mode ?? "all") !== (b.mode ?? "all")) return false;
  const key = (r: SubscriptionRequirement) =>
    JSON.stringify(
      (r.requirements ?? [])
        .map((row) => `${row.provider}:${row.min_tier_rank ?? 1}`)
        .sort()
    );
  return key(a) === key(b);
}

/**
 * The rule half of the subscriptions section. Controlled: `draft` is the
 * unsaved rule (`null` = untouched), stored by the section's one `SaveBar`
 * together with the provider drafts.
 */
export function WorkspaceRequirementCard({
  workspaceId,
  draft,
  onDraftChange
}: Readonly<{
  workspaceId: number;
  draft: SubscriptionRequirement | null;
  onDraftChange: (draft: SubscriptionRequirement) => void;
}>) {
  const t = useTranslations("subscriptionWorkspace");

  const requirementQuery = useQuery({
    queryKey: workspaceQueryKeys.subscriptionRequirement(workspaceId),
    queryFn: () => balancerAdminService.getSubscriptionRequirement(workspaceId),
    refetchOnWindowFocus: false
  });

  // The editor's `availableProviders` contract is "configured AND enabled", and the
  // provider groups above are the only surface that enables them — so read the same
  // list they render instead of hardcoding the provider pair the form builder guessed at.
  // Same query key, so enabling a provider there refreshes the options here.
  const providersQuery = useQuery({
    queryKey: workspaceQueryKeys.subscriptionProviders(workspaceId),
    queryFn: () => balancerAdminService.listSubscriptionProviders(workspaceId),
    refetchOnWindowFocus: false
  });
  const availableProviders = (providersQuery.data?.configs ?? [])
    .filter((config) => config.enabled)
    .map((config) => config.provider);

  const stored = requirementQuery.data?.requirement ?? EMPTY_REQUIREMENT;
  const value = draft ?? stored;

  // Any change to a live rule changes who is admitted, across every tournament in the
  // workspace at once -- so the warning tracks CHANGE, not just emptying. Tightening
  // Boosty 1 -> 3, or `any` -> `all`, retroactively refuses patrons the gate already
  // let in, which mid-tournament is as consequential as disarming it. `draft === null`
  // means untouched, and `sameRule` absorbs an edit-then-revert.
  const changed = draft !== null && !sameRule(value, stored);
  // Emptying is called out separately: it disarms every tournament whose own
  // `require_subscription` toggle is still on, and those then admit everybody without
  // saying so -- the opposite failure from the one above. Both halves matter: without
  // the stored-side test, building up a rule and then deleting the rows again reports
  // "clearing" for a workspace that never had one.
  const disarming =
    (stored.requirements?.length ?? 0) > 0 && (value.requirements?.length ?? 0) === 0;
  // How many tournaments the rule WOULD gate (open, unfinished, toggle on), so the copy
  // can name the blast radius instead of gesturing at it. Fetched with the rule and not
  // refetched on focus, so the copy says "currently", never "right now".
  const enforcingTournaments = requirementQuery.data?.enforcing_tournaments ?? 0;

  if (requirementQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title={t("loadError")}
        onAction={() => void requirementQuery.refetch()}
      />
    );
  }

  return (
    <SettingGroup id="requirement" title={t("title")} description={t("description")}>
      {requirementQuery.isLoading ? (
        // Shaped like the editor: a provider/tier row, then the add button.
        <div aria-busy="true" className="space-y-3">
          <Skeleton className="h-8 w-full max-w-sm" />
          <Skeleton className="h-8 w-32" />
        </div>
      ) : (
        <div className="space-y-4">
          <SubscriptionRequirementEditor
            value={value}
            availableProviders={availableProviders}
            onChange={onDraftChange}
          />

          {changed && (
            <p className="max-w-prose text-caption text-warning">
              {t(disarming ? "warning.disarming" : "warning.changed", {
                count: enforcingTournaments
              })}
            </p>
          )}
        </div>
      )}
    </SettingGroup>
  );
}
