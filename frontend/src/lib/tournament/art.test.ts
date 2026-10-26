import { expect, it } from "vitest";

import type { CatalogEntityRead } from "@/types/catalog.types";
import type { Match } from "@/types/encounter.types";
import { tournamentPicture } from "./art";

const map = (id: number, slug: string, mode = "control") =>
  ({ id, name: slug, slug, image_path: `https://cdn.example/${slug}.jpg`, parent: { slug: mode } }) as CatalogEntityRead;

const played = (...matches: [id: number, mapIndex: number | null, map: CatalogEntityRead | null][]) => ({
  matches: matches.map(([id, map_index, playedMap]) => ({ id, map_index, map: playedMap }) as Match)
});

const CATALOG = [
  map(4, "rialto", "escort"),
  map(1, "workshop-island", "workshop"),
  map(3, "ilios"),
  map(2, "practice-range", "practice-range"),
  map(5, "thames-district", "payload-race"),
  { ...map(6, "grimsvotn", "escort"), image_path: null }
];

const SAMOA = map(7, "samoa");
const KINGS_ROW = map(8, "kings-row");
const NO_STILL = { ...map(9, "grimsvotn"), image_path: null };
const uncovered = { id: 7, cover_image_url: null };

it("keeps the organizer's cover over any map, even before the reads are in", () => {
  const covered = { id: 7, cover_image_url: "https://s3.example/cover.png" };

  expect(tournamentPicture(covered, played([1, 1, SAMOA]), CATALOG)).toBe("https://s3.example/cover.png");
  expect(tournamentPicture(covered, undefined, undefined)).toBe("https://s3.example/cover.png");
});

it("draws a tournament without a cover with the map last played in its latest series", () => {
  expect(tournamentPicture(uncovered, played([30, 3, KINGS_ROW], [31, 4, SAMOA], [29, 2, NO_STILL]), CATALOG)).toBe(
    SAMOA.image_path
  );
  // Logs never bound to a series position: the match stored last.
  expect(tournamentPicture(uncovered, played([42, null, KINGS_ROW], [41, null, SAMOA]), CATALOG)).toBe(
    KINGS_ROW.image_path
  );
  // A later map without a still is skipped, not drawn as nothing.
  expect(tournamentPicture(uncovered, played([50, 1, SAMOA], [51, 2, NO_STILL]), CATALOG)).toBe(SAMOA.image_path);
});

it("waits for the latest series before picking a map, and for the catalog only when nothing was played", () => {
  expect(tournamentPicture(uncovered, undefined, CATALOG)).toBeUndefined();
  expect(tournamentPicture(uncovered, null, undefined)).toBeUndefined();
  expect(tournamentPicture(uncovered, played([1, 1, SAMOA]), undefined)).toBe(SAMOA.image_path);
});

it("fixes a tournament with nothing played to one map whatever order the catalog came in", () => {
  // The home page reads the catalog by id, the tournament list by name: the
  // same tournament must still get the same map on both.
  const byName = [...CATALOG].sort((left, right) => left.name.localeCompare(right.name));
  const reversed = [...CATALOG].reverse();

  for (const id of [113, 114, 115, 123, 127]) {
    const picture = tournamentPicture({ id, cover_image_url: null }, null, byName);
    expect(picture).toBe(tournamentPicture({ id, cover_image_url: null }, played(), reversed));
    // Never an empty room, a test range, a still with its name printed on it, or a map without a still.
    expect(["https://cdn.example/rialto.jpg", "https://cdn.example/ilios.jpg"]).toContain(picture);
  }
});

it("has no picture without a cover, a played map or a map still", () => {
  expect(tournamentPicture(uncovered, null, [])).toBeNull();
  expect(tournamentPicture(uncovered, played([1, 1, NO_STILL]), [CATALOG[1]])).toBeNull();
});
