import { describe, expect, it } from "vitest";

import { tournamentMapPips } from "@/app/(site)/users/components/overview/map-results";
import type { EncounterWithUserStats } from "@/types/user.types";

const encounter = (
  id: number,
  userTeamId: number,
  homeTeamId: number,
  maps: Array<{ home: number; away: number }>
): EncounterWithUserStats =>
  ({
    id,
    user_team_id: userTeamId,
    home_team_id: homeTeamId,
    matches: maps.map((score, index) => ({
      id: id * 10 + index,
      score,
      map_id: index + 1
    }))
  }) as EncounterWithUserStats;

describe("tournamentMapPips", () => {
  it("returns null when no maps were recorded", () => {
    expect(tournamentMapPips([encounter(1, 1, 1, [])], 7)).toBeNull();
  });

  it("keeps series order and reads scores from the viewer's side", () => {
    const pips = tournamentMapPips(
      [
        encounter(1, 10, 10, [
          { home: 2, away: 0 },
          { home: 0, away: 1 }
        ]),
        encounter(2, 10, 20, [{ home: 1, away: 1 }])
      ],
      7
    );
    expect(pips).toEqual(["win", "loss", "draw"]);
  });
});
