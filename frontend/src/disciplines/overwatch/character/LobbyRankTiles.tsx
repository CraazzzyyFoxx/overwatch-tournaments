"use client";

import { useTranslations } from "next-intl";

import { isRankedEntry, LobbyStatGrid, type LobbyStatTile } from "@/components/profile/LobbyStatGrid";
import type { SlotProps } from "@/disciplines/types";

/** Overwatch's lobby-ranked tournament stats in their render order (design-book §3), each with its own label. */
const STAT_ORDER: { key: string; labelKey: string }[] = [
  { key: "kda", labelKey: "users.overview.lastTournament.stat.kda" },
  { key: "impact_rank", labelKey: "users.overview.lastTournament.stat.mvpScore" },
  { key: "hero_damage_dealt", labelKey: "users.overview.lastTournament.stat.dmgPerMap" },
  { key: "eliminations", labelKey: "users.overview.lastTournament.stat.elims" },
  { key: "deaths", labelKey: "users.overview.lastTournament.stat.deaths" },
  { key: "assists", labelKey: "users.overview.lastTournament.stat.assists" },
  { key: "kd", labelKey: "users.overview.lastTournament.stat.kd" },
  { key: "damage_delta", labelKey: "users.overview.lastTournament.stat.dmgDelta" }
];
/** The one signed stat: a damage lead over the opponent reads good, a deficit bad. */
const SIGNED_STAT = "damage_delta";

/** The card's compact value: thousands as `1.2k`, everything else to two decimals (unchanged from the core card). */
const compactNumber = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 1000) {
    return `${(value / 1000).toFixed(1)}k`;
  }
  return value.toFixed(2);
};

/** The overview tournament card's lobby-rank tiles for an Overwatch tournament (the `lobbyRankTiles` slot). */
const LobbyRankTiles = ({ stats, onOpen }: SlotProps["lobbyRankTiles"]) => {
  const t = useTranslations();
  const tiles: LobbyStatTile[] = [];
  for (const def of STAT_ORDER) {
    const entry = stats[def.key];
    if (!isRankedEntry(entry)) continue;
    const signed = def.key === SIGNED_STAT;
    // A negative delta already shows its sign; a positive one needs the `+` to read as a delta, not a plain count.
    const formatted = compactNumber(entry.value);
    tiles.push({
      stat: def.key,
      label: t(def.labelKey as Parameters<typeof t>[0]),
      rank: entry.rank,
      total: entry.total,
      value: signed && entry.value >= 0 ? `+${formatted}` : formatted,
      highlight: signed ? (entry.value >= 0 ? "good" : "bad") : undefined
    });
  }
  return <LobbyStatGrid tiles={tiles} onOpen={onOpen} />;
};

export default LobbyRankTiles;
