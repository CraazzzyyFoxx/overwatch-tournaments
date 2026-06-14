// Rarity tiers, keyed off the share of players that own an achievement
// (`rarity` is a 0..1 fraction → percent). Rarer = lower percent.
//   Legendary < 1% · Epic 1–5% · Rare 5–15% · Uncommon 15–30% · Common ≥ 30%

export type Rarity = "legendary" | "epic" | "rare" | "uncommon" | "common";

export const RARITY_ORDER: Rarity[] = ["legendary", "epic", "rare", "uncommon", "common"];

export const classifyRarity = (rarityPercent: number): Rarity => {
  if (rarityPercent < 1) return "legendary";
  if (rarityPercent < 5) return "epic";
  if (rarityPercent < 15) return "rare";
  if (rarityPercent < 30) return "uncommon";
  return "common";
};

export const RARITY_TITLES: Record<Rarity, string> = {
  legendary: "Legendary · < 1% of all players",
  epic: "Epic · 1-5%",
  rare: "Rare · 5-15%",
  uncommon: "Uncommon · 15-30%",
  common: "Common · > 30%"
};

export const RARITY_RANGE: Record<Rarity, string> = {
  legendary: "< 1% earn",
  epic: "1-5%",
  rare: "5-15%",
  uncommon: "15-30%",
  common: "> 30%"
};
