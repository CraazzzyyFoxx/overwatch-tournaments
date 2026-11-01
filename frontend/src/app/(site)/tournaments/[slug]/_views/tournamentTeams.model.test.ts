import { describe, expect, it } from "vitest";

import type { Player } from "@/types/team.types";

import { playerMatches } from "./tournamentTeams.model";
import { rosterNames } from "./tournamentOverview.model";

const player = (display: Player["display"]) => ({ display }) as Player;

describe("a roster player's name in a game's tournament", () => {
  const riot = player({ name: "Faker", tag: "#KR1", canonical: "Lee#1234", snapshot: "OldFaker#EUW" });

  it("is found by the name shown, the account name or the one registered with", () => {
    expect(playerMatches(riot, "faker#kr1")).toBe(true);
    expect(playerMatches(riot, "lee")).toBe(true);
    expect(playerMatches(riot, "oldfaker")).toBe(true);
    expect(playerMatches(riot, "nobody")).toBe(false);
  });

  it("is listed without its tag", () => {
    const team = { players: [riot, player({ name: "Nyx", tag: null, canonical: null, snapshot: null })] };
    expect(rosterNames(team as never)).toBe("Faker · Nyx");
  });
});
