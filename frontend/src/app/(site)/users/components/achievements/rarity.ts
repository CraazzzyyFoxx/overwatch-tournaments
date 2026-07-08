// Rarity tiers, keyed off the share of players that own an achievement
// (`rarity` is a 0..1 fraction → percent). Rarer = lower percent.
//   Mythic < 1% · Legendary 1–5% · Epic 5–15% · Rare 15–30% · Uncommon 30–50% · Common > 50%

import type { useTranslations } from "next-intl";

// Loose translator alias matching next-intl's `useTranslations()` return type so
// callers can hand their `t` straight through (strictFunctionTypes-safe).
type Translate = ReturnType<typeof useTranslations>;

export type Rarity = "mythic" | "legendary" | "epic" | "rare" | "uncommon" | "common";

export const RARITY_ORDER: Rarity[] = ["mythic", "legendary", "epic", "rare", "uncommon", "common"];

export const classifyRarity = (rarityPercent: number): Rarity => {
  if (rarityPercent < 1) return "mythic";
  if (rarityPercent < 5) return "legendary";
  if (rarityPercent < 15) return "epic";
  if (rarityPercent < 30) return "rare";
  if (rarityPercent < 50) return "uncommon";
  return "common";
};

// Localized tier titles (e.g. "Mythic · < 1% of all players"), keyed by rarity.
export const rarityTitles = (t: Translate): Record<Rarity, string> => ({
  mythic: t("users.achievements.rarity.mythic.title"),
  legendary: t("users.achievements.rarity.legendary.title"),
  epic: t("users.achievements.rarity.epic.title"),
  rare: t("users.achievements.rarity.rare.title"),
  uncommon: t("users.achievements.rarity.uncommon.title"),
  common: t("users.achievements.rarity.common.title")
});

// Localized compact ranges (e.g. "< 1% earn"), keyed by rarity.
export const rarityRanges = (t: Translate): Record<Rarity, string> => ({
  mythic: t("users.achievements.rarity.mythic.range"),
  legendary: t("users.achievements.rarity.legendary.range"),
  epic: t("users.achievements.rarity.epic.range"),
  rare: t("users.achievements.rarity.rare.range"),
  uncommon: t("users.achievements.rarity.uncommon.range"),
  common: t("users.achievements.rarity.common.range")
});
