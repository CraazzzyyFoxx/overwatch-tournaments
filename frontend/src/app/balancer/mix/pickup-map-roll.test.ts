import { describe, expect, it } from "vitest";

import type { MapRead } from "@/types/map.types";

import { rollNextMap, rollableModes } from "./pickup-map-roll";

const CONTROL = { id: 1, name: "Control", slug: "control", image_path: "", description: "", aliases: [] };
const CLASH = { id: 2, name: "Clash", slug: "clash", image_path: "", description: "", aliases: [] };
const DEATHMATCH = { id: 3, name: "Deathmatch", slug: "deathmatch", image_path: "", description: "", aliases: [] };

function map(id: number, gamemode: typeof CONTROL, overrides: Partial<MapRead> = {}): MapRead {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name: `Map ${id}`,
    image_path: "",
    gamemode_id: gamemode.id,
    in_competitive: true,
    aliases: [],
    gamemode,
    ...overrides,
  };
}

// Three Control maps, one Clash map, one arcade-only Deathmatch map.
const CATALOGUE = [
  map(10, CONTROL),
  map(11, CONTROL),
  map(12, CONTROL),
  map(20, CLASH),
  map(30, DEATHMATCH, { in_competitive: false }),
];

/** A `random` that hands out the given values in order, then 0. */
function sequence(...values: number[]): () => number {
  const queue = [...values];
  return () => queue.shift() ?? 0;
}

describe("rollableModes", () => {
  it("lists only modes that have a competitive map, name-ordered", () => {
    expect(rollableModes(CATALOGUE).map((mode) => mode.name)).toEqual(["Clash", "Control"]);
  });
});

describe("rollNextMap", () => {
  it("rolls the mode first, so a one-map mode is as likely as a three-map one", () => {
    // 0.6 over two modes -> Clash (index 1); over four maps it would have been
    // Control's third map (index 2) -- the very bias the two-stage roll avoids.
    const rolled = rollNextMap(CATALOGUE, { gamemodeId: null, playedMapIds: [], random: sequence(0.6, 0) });
    expect(rolled?.id).toBe(20);
  });

  it("stays inside the chosen mode", () => {
    const rolled = rollNextMap(CATALOGUE, { gamemodeId: CONTROL.id, playedMapIds: [], random: sequence(0.99) });
    expect(rolled?.id).toBe(12);
  });

  it("skips maps this mix has played while any fresh one is left, then reopens the pool", () => {
    const fresh = rollNextMap(CATALOGUE, {
      gamemodeId: CONTROL.id,
      playedMapIds: [10, 11],
      random: sequence(0),
    });
    expect(fresh?.id).toBe(12);

    const exhausted = rollNextMap(CATALOGUE, {
      gamemodeId: CONTROL.id,
      playedMapIds: [10, 11, 12],
      random: sequence(0),
    });
    expect(exhausted?.id).toBe(10);
  });

  it("drops a fully played mode from the mode roll until everything is played", () => {
    // Clash's only map is played, so 0.6 (which picked Clash above) now lands on Control.
    const rolled = rollNextMap(CATALOGUE, { gamemodeId: null, playedMapIds: [20], random: sequence(0.6, 0) });
    expect(rolled?.gamemode_id).toBe(CONTROL.id);
  });

  it("never rolls an arcade-only map, and returns null when nothing qualifies", () => {
    expect(rollNextMap(CATALOGUE, { gamemodeId: DEATHMATCH.id, playedMapIds: [] })).toBeNull();
    expect(rollNextMap([], { gamemodeId: null, playedMapIds: [] })).toBeNull();
  });
});
