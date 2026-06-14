import { describe, expect, it } from "bun:test";

import {
  groupTournamentsByLeague,
  leagueKey
} from "@/app/(site)/users/components/tournaments/tournaments-history.helpers";
import type { UserTournament } from "@/types/user.types";

const buildTournament = (id: number, name: string, isLeague: boolean): UserTournament =>
  ({
    id,
    name,
    is_league: isLeague
  }) as UserTournament;

describe("leagueKey", () => {
  it("extracts the prefix before the pipe separator", () => {
    expect(leagueKey(buildTournament(1, "Winter League | Division 2", true))).toBe("Winter League");
  });

  it("returns the whole name when there is no separator", () => {
    expect(leagueKey(buildTournament(1, "Open Cup", false))).toBe("Open Cup");
  });
});

describe("groupTournamentsByLeague", () => {
  it("collapses consecutive same-league divisions into one group", () => {
    const tournaments = [
      buildTournament(1, "Winter League | Division 1", true),
      buildTournament(2, "Winter League | Division 2", true),
      buildTournament(3, "Winter League | Division 3", true)
    ];

    const result = groupTournamentsByLeague(tournaments);

    expect(result).toHaveLength(1);
    expect(Array.isArray(result[0])).toBe(true);
    expect((result[0] as UserTournament[]).map((t) => t.id)).toEqual([1, 2, 3]);
  });

  it("keeps non-league tournaments as standalone entries", () => {
    const tournaments = [
      buildTournament(1, "Open Cup", false),
      buildTournament(2, "Charity Bowl", false)
    ];

    const result = groupTournamentsByLeague(tournaments);

    expect(result).toHaveLength(2);
    expect(Array.isArray(result[0])).toBe(false);
    expect((result[0] as UserTournament).id).toBe(1);
  });

  it("splits adjacent groups belonging to different leagues", () => {
    const tournaments = [
      buildTournament(1, "Winter League | Division 1", true),
      buildTournament(2, "Winter League | Division 2", true),
      buildTournament(3, "Summer League | Division 1", true)
    ];

    const result = groupTournamentsByLeague(tournaments);

    expect(result).toHaveLength(2);
    expect((result[0] as UserTournament[]).map((t) => t.id)).toEqual([1, 2]);
    expect((result[1] as UserTournament[]).map((t) => t.id)).toEqual([3]);
  });

  it("preserves order when leagues and standalone tournaments interleave", () => {
    const tournaments = [
      buildTournament(1, "Open Cup", false),
      buildTournament(2, "Winter League | Division 1", true),
      buildTournament(3, "Winter League | Division 2", true),
      buildTournament(4, "Charity Bowl", false)
    ];

    const result = groupTournamentsByLeague(tournaments);

    expect(result).toHaveLength(3);
    expect((result[0] as UserTournament).id).toBe(1);
    expect((result[1] as UserTournament[]).map((t) => t.id)).toEqual([2, 3]);
    expect((result[2] as UserTournament).id).toBe(4);
  });
});
