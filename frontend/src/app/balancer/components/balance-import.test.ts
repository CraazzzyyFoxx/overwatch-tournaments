import { describe, expect, it } from "vitest";

import { parseImportedBalancePayload } from "./balance-import";

const player = {
  uuid: 297,
  name: "Player#1234",
  assigned_rating: 2600,
  role_discomfort: 100,
  is_captain: true,
  role_preferences: ["Tank", "Damage"],
  all_ratings: { Tank: 2600, Damage: 2400 },
  sub_role: null
};

function payloadWith(team: Record<string, unknown>): string {
  return JSON.stringify({ teams: [team] });
}

describe("parseImportedBalancePayload", () => {
  it("parses a downloaded balance payload", () => {
    const payload = parseImportedBalancePayload(
      JSON.stringify({
        teams: [
          {
            id: 4,
            name: "Team A",
            average_mmr: 2500,
            rating_variance: 12.5,
            total_discomfort: 100,
            max_discomfort: 100,
            roster: { Tank: [player], Damage: [], Support: [] }
          }
        ],
        statistics: { average_mmr: 2500, mmr_std_dev: 0 },
        benched_players: [{ uuid: "298", name: "Bench#1", assigned_rating: 2000 }]
      })
    );

    const team = payload.teams[0];
    expect(team.id).toBe(4);
    expect(team.average_mmr).toBe(2500);
    expect(team.rating_variance).toBe(12.5);
    expect(team.roster.Tank[0].uuid).toBe("297");
    expect(team.roster.Tank[0].is_captain).toBe(true);
    expect(payload.statistics?.average_mmr).toBe(2500);
    expect(payload.benched_players?.[0].name).toBe("Bench#1");
  });

  it("fills missing roster buckets, ids and derived aggregates", () => {
    const payload = parseImportedBalancePayload(
      payloadWith({ name: "Team A", roster: { Tank: [player] } })
    );

    const team = payload.teams[0];
    expect(team.id).toBe(1);
    expect(team.average_mmr).toBe(2600);
    expect(team.total_discomfort).toBe(100);
    expect(team.max_discomfort).toBe(100);
    expect(team.roster.Damage).toEqual([]);
    expect(team.roster.Support).toEqual([]);
  });

  // The save endpoint validates statistics against the solver's `Statistics`
  // schema: these four are required, so a file that omits the block must still
  // produce them or the import previews fine and 422s on save.
  it("derives the statistics the save endpoint requires when the file omits them", () => {
    const payload = parseImportedBalancePayload(
      payloadWith({ name: "Team A", roster: { Tank: [player] } })
    );

    expect(payload.statistics).toMatchObject({
      average_mmr: 2600,
      mmr_std_dev: 0,
      total_teams: 1,
      players_per_team: 1
    });
  });

  it("defaults optional player fields so the payload stays saveable", () => {
    const payload = parseImportedBalancePayload(
      payloadWith({
        name: "Team A",
        roster: { Tank: [{ uuid: "1", name: "P#1", assigned_rating: 1000 }] }
      })
    );

    const parsed = payload.teams[0].roster.Tank[0];
    expect(parsed.role_discomfort).toBe(0);
    expect(parsed.is_captain).toBe(false);
    expect(parsed.is_flex).toBe(false);
    expect(parsed.role_preferences).toEqual([]);
    expect(parsed.all_ratings).toEqual({});
    expect(parsed.all_discomforts).toEqual({});
    expect(parsed.sub_role).toBe(null);
  });

  it("rejects non-JSON files", () => {
    expect(() => parseImportedBalancePayload("not json")).toThrowError(/not valid JSON/);
  });

  it("rejects payloads without teams", () => {
    expect(() => parseImportedBalancePayload(JSON.stringify({ data: { teams: [] } }))).toThrowError(
      /"teams" array/
    );
    expect(() => parseImportedBalancePayload(JSON.stringify({ teams: [] }))).toThrowError(
      /no teams/
    );
  });

  it("rejects the legacy camelCase player shape by name", () => {
    expect(() =>
      parseImportedBalancePayload(
        payloadWith({
          name: "Team A",
          roster: { Tank: [{ uuid: "1", name: "P#1", rating: 1000, isCaptain: true }] }
        })
      )
    ).toThrowError(/assigned_rating/);
  });

  it("rejects unknown roster roles instead of dropping their players", () => {
    expect(() =>
      parseImportedBalancePayload(payloadWith({ name: "Team A", roster: { DPS: [player] } }))
    ).toThrowError(/unsupported roster role "DPS"/);
  });

  it("names the offending team and player", () => {
    expect(() =>
      parseImportedBalancePayload(payloadWith({ name: "Team A", roster: { Tank: [{}] } }))
    ).toThrowError(/Team "Team A" Tank player #1 is missing "uuid"/);
    expect(() => parseImportedBalancePayload(payloadWith({ roster: {} }))).toThrowError(
      /Team #1 is missing "name"/
    );
  });
});
