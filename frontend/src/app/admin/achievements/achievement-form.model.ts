import type {
  AchievementRule,
  AchievementRuleCreateInput,
  AchievementRuleUpdateInput,
} from "@/types/admin.types";

export const emptyAchievementForm: AchievementRuleCreateInput = {
  slug: "",
  name: "",
  description_ru: "",
  description_en: "",
  category: "overall",
  scope: "global",
  grain: "user",
  condition_tree: {},
  depends_on: [],
  enabled: true,
};

/**
 * The editable half of a rule. Key order matters: the dirty check is a
 * `JSON.stringify` comparison against the form state, which is built by
 * spreading this same object.
 */
export function achievementFormData(rule: AchievementRule): AchievementRuleUpdateInput {
  return {
    name: rule.name,
    description_ru: rule.description_ru,
    description_en: rule.description_en,
    image_url: rule.image_url,
    hero_id: rule.hero_id,
    category: rule.category,
    scope: rule.scope,
    grain: rule.grain,
    condition_tree: rule.condition_tree,
    depends_on: rule.depends_on,
    enabled: rule.enabled,
    min_tournament_id: rule.min_tournament_id,
  };
}

/** The list dialog also shows the slug — read-only when editing, but part of the form. */
export function achievementFormDataWithSlug(rule: AchievementRule): AchievementRuleUpdateInput {
  return { slug: rule.slug, ...achievementFormData(rule) };
}

/** How many actual predicates a condition tree holds, ignoring the logic wrapping them. */
export function countLeafConditions(node: Record<string, unknown>): number {
  if (node.AND) return (node.AND as Record<string, unknown>[]).reduce((s, c) => s + countLeafConditions(c), 0);
  if (node.OR) return (node.OR as Record<string, unknown>[]).reduce((s, c) => s + countLeafConditions(c), 0);
  if (node.NOT) return countLeafConditions(node.NOT as Record<string, unknown>);
  return 1;
}

export function groupRulesByCategory(rules: AchievementRule[]): Record<string, AchievementRule[]> {
  return rules.reduce<Record<string, AchievementRule[]>>((acc, rule) => {
    (acc[rule.category] ??= []).push(rule);
    return acc;
  }, {});
}
