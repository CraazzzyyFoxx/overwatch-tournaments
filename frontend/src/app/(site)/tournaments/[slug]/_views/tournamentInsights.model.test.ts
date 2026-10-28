import { describe, expect, it } from "vitest";

import type { HeroBan, MapBan } from "@/lib/tournament/insights-query";

import { aggregateBans, balanceColumns, oneTricks } from "./tournamentInsights.model";

type Card = { id: string; weight: number };
const cards = (...weights: number[]): Card[] =>
  weights.map((weight, index) => ({ id: String.fromCharCode(97 + index), weight }));
const ids = (items: readonly Card[]) => items.map((item) => item.id);
const split = (items: Card[]) => {
  const { left, right, tail } = balanceColumns(items, (item) => item.weight);
  return { left: ids(left), right: ids(right), tail: tail?.id ?? null };
};

describe("balanceColumns", () => {
  it("cuts a reading-order prefix into the left column, balanced by weight", () => {
    expect(split(cards(3, 1, 1, 1))).toEqual({ left: ["a"], right: ["b", "c", "d"], tail: null });
    expect(split(cards(1, 1, 1, 3))).toEqual({ left: ["a", "b", "c"], right: ["d"], tail: null });
  });

  it("lets the last card run under the columns when that evens them", () => {
    expect(split(cards(1, 1, 1, 1, 1))).toEqual({ left: ["a", "b"], right: ["c", "d"], tail: "e" });
  });

  it("keeps the last card in the columns when they are already even", () => {
    expect(split(cards(1, 1, 1, 1))).toEqual({ left: ["a", "b"], right: ["c", "d"], tail: null });
  });

  it("never yields a tail for fewer than three cards", () => {
    // With a third card in front, [1, 5] would tail the 5; two cards always stay side by side.
    expect(split(cards(1, 5))).toEqual({ left: ["a"], right: ["b"], tail: null });
    expect(split(cards(2)).tail).toBeNull();
    expect(split([])).toEqual({ left: [], right: [], tail: null });
  });
});

const blind = (encounterId: number, heroId: number): HeroBan => ({
  encounterId,
  heroId,
  firstMap: true,
  targetPlayerId: null
});
const targeted = (encounterId: number, heroId: number, playerId: number, times = 1): HeroBan[] =>
  Array.from({ length: times }, () => ({
    encounterId,
    heroId,
    firstMap: false,
    targetPlayerId: playerId
  }));
const map = (encounterId: number, mapId: number, picked: boolean): MapBan => ({
  encounterId,
  mapId,
  picked
});

const HERO_BANS: HeroBan[] = [
  blind(1, 10),
  ...targeted(1, 10, 100),
  ...targeted(1, 20, 100),
  blind(2, 10),
  ...targeted(2, 30, 200)
];
const MAP_BANS: MapBan[] = [
  map(1, 5, false),
  map(1, 6, true),
  map(1, 7, false),
  map(2, 5, false),
  map(2, 6, true),
  map(2, 7, true)
];

describe("aggregateBans", () => {
  it("splits each hero's bans into blind and targeted, counting the series it was banned in", () => {
    const bans = aggregateBans(HERO_BANS, MAP_BANS);
    expect(bans?.series).toBe(2);
    expect(bans?.totalHeroBans).toBe(5);
    expect(bans?.heroes).toEqual([
      { id: 10, bans: 3, series: 2, blind: 2, targeted: 1 },
      { id: 20, bans: 1, series: 1, blind: 0, targeted: 1 },
      { id: 30, bans: 1, series: 1, blind: 0, targeted: 1 }
    ]);
    expect(bans?.targets).toEqual([
      {
        playerId: 100,
        bans: 2,
        heroes: [
          { id: 10, bans: 1 },
          { id: 20, bans: 1 }
        ]
      },
      { playerId: 200, bans: 1, heroes: [{ id: 30, bans: 1 }] }
    ]);
  });

  it("counts maps picked and banned, most picked first, then least banned", () => {
    expect(aggregateBans(HERO_BANS, MAP_BANS)?.maps).toEqual([
      { id: 6, banned: 0, picked: 2 },
      { id: 7, banned: 1, picked: 1 },
      { id: 5, banned: 2, picked: 0 }
    ]);
  });

  it("aggregates only the series `keep` admits", () => {
    const bans = aggregateBans(HERO_BANS, MAP_BANS, (encounterId) => encounterId === 2);
    expect(bans?.series).toBe(1);
    expect(bans?.totalHeroBans).toBe(2);
    expect(bans?.heroes).toEqual([
      { id: 10, bans: 1, series: 1, blind: 1, targeted: 0 },
      { id: 30, bans: 1, series: 1, blind: 0, targeted: 1 }
    ]);
    expect(bans?.targets.map((row) => row.playerId)).toEqual([200]);
    expect(bans?.maps).toEqual([
      { id: 6, banned: 0, picked: 1 },
      { id: 7, banned: 0, picked: 1 },
      { id: 5, banned: 1, picked: 0 }
    ]);
  });

  it("is null when nothing was banned or picked", () => {
    expect(aggregateBans([], [])).toBeNull();
    expect(aggregateBans(HERO_BANS, MAP_BANS, () => false)).toBeNull();
  });

  it("still reports a pool that only saw map bans", () => {
    const bans = aggregateBans([], [map(1, 5, false)]);
    expect(bans).toMatchObject({ series: 0, totalHeroBans: 0, heroes: [], targets: [] });
    expect(bans?.maps).toEqual([{ id: 5, banned: 1, picked: 0 }]);
  });
});

describe("oneTricks", () => {
  const bans = aggregateBans(
    [
      // 6 bans, 5 of them on one hero: the clearest one-trick.
      ...targeted(1, 10, 100, 5),
      ...targeted(1, 20, 100),
      // Half and half, 4 + 4.
      ...targeted(2, 30, 200, 4),
      ...targeted(2, 31, 200, 4),
      // Half and half too, but 5 + 5: the same share on more bans ranks above.
      ...targeted(3, 50, 400, 5),
      ...targeted(3, 51, 400, 5),
      // Always the same hero, but only four bans.
      ...targeted(4, 40, 300, 4)
    ],
    []
  );

  it("ranks players by their top hero's share of their bans, ties by that hero's bans", () => {
    expect(oneTricks(bans)).toEqual([
      { playerId: 100, heroId: 10, heroBans: 5, bans: 6, share: 5 / 6 },
      { playerId: 400, heroId: 50, heroBans: 5, bans: 10, share: 0.5 },
      { playerId: 200, heroId: 30, heroBans: 4, bans: 8, share: 0.5 }
    ]);
  });

  it("leaves out players with fewer bans than `minBans`", () => {
    expect(oneTricks(bans, 4)[0]).toEqual({
      playerId: 300,
      heroId: 40,
      heroBans: 4,
      bans: 4,
      share: 1
    });
    expect(oneTricks(bans, 9).map((row) => row.playerId)).toEqual([400]);
  });

  it("is empty without bans", () => {
    expect(oneTricks(null)).toEqual([]);
  });
});
