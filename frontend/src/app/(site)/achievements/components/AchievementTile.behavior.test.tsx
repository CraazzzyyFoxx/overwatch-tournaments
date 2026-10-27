// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Achievement } from "@/types/achievement.types";
import type { DisciplineDescriptor } from "@/types/discipline.types";

import AchievementTile from "./AchievementTile";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const GAMES = new Map(
  (
    [
      { code: "overwatch", name: "Overwatch", short_name: "OW", icon: null, enabled: true },
      { code: "lol", name: "League of Legends", short_name: "LoL", icon: null, enabled: true }
    ] as DisciplineDescriptor[]
  ).map((game) => [game.code, game])
);

const RULE = {
  id: 1,
  name: "Sharpshooter",
  slug: "sharpshooter",
  image_url: "/sharpshooter.webp",
  rarity: 0.1,
  count: 2,
  description_ru: null,
  description_en: null
};

let root: Root;
let container: HTMLElement;

beforeEach(() => {
  container = document.body.appendChild(document.createElement("div"));
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function render(discipline: string, games?: Map<string, DisciplineDescriptor>) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
        <AchievementTile achievement={{ ...RULE, discipline } as unknown as Achievement} games={games} />
      </NextIntlClientProvider>
    );
  });
  // What a reader gets from the tile's numbers line: the decorative mark is hidden, the game's name is not.
  const meta = container.querySelector("[data-tile-meta]")?.cloneNode(true) as HTMLElement;
  meta.querySelectorAll('[aria-hidden="true"]').forEach((node) => node.remove());
  return meta.textContent;
}

describe("the achievement tile's game mark", () => {
  it("names the rule's game when the catalogue spans games, an unknown game by its code", async () => {
    expect(await render("lol", GAMES)).toBe("League of Legends10.00%2");
    expect(await render("retired", GAMES)).toBe("retired10.00%2");
  });

  it("names no game when the catalogue is one game's", async () => {
    expect(await render("lol")).toBe("10.00%2");
  });
});
