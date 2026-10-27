// Rarity tiers, keyed off the share of players that own an achievement
// (`rarity` is a 0..1 fraction → percent). Rarer = lower percent.
//   Mythic < 1% · Legendary 1–5% · Epic 5–15% · Rare 15–30% · Uncommon 30–50% · Common > 50%

import type { useTranslations } from "next-intl";

// Loose translator alias matching next-intl's `useTranslations()` return type so
// callers can hand their `t` straight through (strictFunctionTypes-safe).
type Translate = ReturnType<typeof useTranslations<never>>;

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

// Sets the `--rar` HSL triplet for a tier (a triplet, so `hsl(var(--rar) / a)`
// alpha tints work; `globals.css` holds the "common" fallback on :root). Every
// rarity-tinted element (tile, crest, dot, pill) reads `hsl(var(--rar))`, so it
// only needs this one class on an ancestor. Literal strings: Tailwind reads them.
const RARITY_VAR_CLASS: Record<Rarity, string> = {
  mythic: "[--rar:40_96%_62%]",
  legendary: "[--rar:350_80%_64%]",
  epic: "[--rar:270_72%_68%]",
  rare: "[--rar:210_82%_64%]",
  uncommon: "[--rar:150_57%_55%]",
  common: "[--rar:215_14%_60%]"
};

export const rarityVarClass = (rarity: Rarity): string => RARITY_VAR_CLASS[rarity];

// Localized compact ranges (e.g. "< 1% earn"), keyed by rarity.
export const rarityRanges = (t: Translate): Record<Rarity, string> => ({
  mythic: t("users.achievements.rarity.mythic.range"),
  legendary: t("users.achievements.rarity.legendary.range"),
  epic: t("users.achievements.rarity.epic.range"),
  rare: t("users.achievements.rarity.rare.range"),
  uncommon: t("users.achievements.rarity.uncommon.range"),
  common: t("users.achievements.rarity.common.range")
});

// Achievements carry a paired `*_ru` / `*_en` text field. Picking `ru || en`
// unconditionally served Russian copy to English readers whenever the RU field
// was filled, so the variant is chosen from the active locale and only falls
// back to the other language when the preferred one is empty.
export const localizedText = (
  locale: string,
  ru: string | null | undefined,
  en: string | null | undefined
): string => (locale.startsWith("ru") ? ru || en : en || ru) || "";
