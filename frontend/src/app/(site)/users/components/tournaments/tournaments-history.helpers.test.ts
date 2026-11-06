import { describe, expect, it } from "vitest";

import { tournamentAggregate } from "@/app/(site)/users/components/tournaments/tournaments-history.helpers";
import type { UserTournament } from "@/types/user.types";

describe("tournamentAggregate", () => {
  it("reads one tournament's record and map tallies", () => {
    const t = { won: 3, lost: 1, draw: 2, maps_won: 7, maps_lost: 5 } as UserTournament;

    expect(tournamentAggregate(t)).toEqual({ won: 3, lost: 1, draw: 2, mapsWon: 7, mapsLost: 5 });
  });

  it("counts an absent tally as zero", () => {
    expect(tournamentAggregate({} as UserTournament)).toEqual({ won: 0, lost: 0, draw: 0, mapsWon: 0, mapsLost: 0 });
  });
});
