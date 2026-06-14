// Rarity tiers, keyed off the share of players that own an achievement
// (`rarity` is a 0..1 fraction → percent). Rarer = lower percent.
//   Mythic < 1% · Legendary 1–5% · Epic 5–15% · Rare 15–30% · Uncommon 30–50% · Common > 50%

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

export const RARITY_TITLES: Record<Rarity, string> = {
  mythic: "Mythic · < 1% of all players",
  legendary: "Legendary · 1-5%",
  epic: "Epic · 5-15%",
  rare: "Rare · 15-30%",
  uncommon: "Uncommon · 30-50%",
  common: "Common · > 50%"
};

export const RARITY_RANGE: Record<Rarity, string> = {
  mythic: "< 1% earn",
  legendary: "1-5%",
  epic: "5-15%",
  rare: "15-30%",
  uncommon: "30-50%",
  common: "> 50%"
};
