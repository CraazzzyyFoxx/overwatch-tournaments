"use client";

import { useTranslations } from "next-intl";

import { PROVIDER_LABELS, requirementClauses } from "@/lib/registration/subscription-requirement";
import type { SubscriptionRequirement } from "@/types/registration.types";

/**
 * The rule as one sentence, e.g. `Boosty level 2 or Twitch`.
 *
 * The join lives here rather than at the call sites: a component that glued
 * `t("clause")` results together with a literal separator would bake English
 * word order and English punctuation into every locale.
 */
export function useRequirementDescription(
  requirement: SubscriptionRequirement | undefined | null
): string {
  const t = useTranslations("subscriptionRequirement.rule");
  const clauses = requirementClauses(requirement);
  if (clauses.length === 0) return "";

  return clauses
    .map((clause) => {
      const provider = PROVIDER_LABELS[clause.provider] ?? clause.provider;
      return clause.minTier === null
        ? t("clauseAnyTier", { provider })
        : t("clause", { provider, tier: clause.minTier });
    })
    .join((requirement?.mode ?? "all") === "any" ? t("or") : t("and"));
}
