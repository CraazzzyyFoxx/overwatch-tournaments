import { describe, expect, it } from "vitest";

import type { StageSummary, TournamentStatus } from "@/types/tournament.types";

import { buildTournamentSectionNav, getTournamentPhaseNoteKey } from "./tournament-section-nav";

const tournamentId = "72";

function stage(overrides: Partial<StageSummary> = {}): StageSummary {
  return {
    id: 9,
    tournament_id: Number(tournamentId),
    name: "Playoffs",
    description: null,
    stage_type: "single_elimination",
    max_rounds: 3,
    advance_count: null,
    split_lower_bracket: false,
    order: 1,
    is_active: true,
    is_completed: false,
    settings_json: null,
    challonge_id: null,
    challonge_slug: null,
    ...overrides
  };
}

function model(
  status: TournamentStatus,
  pathname = `/tournaments/${tournamentId}/participants`,
  stages: StageSummary[] = [stage()]
) {
  return buildTournamentSectionNav({
    tournamentId,
    status,
    stages,
    teamFormation: "draft",
    pathname
  });
}

describe("buildTournamentSectionNav", () => {
  it.each<TournamentStatus>(["registration", "draft", "check_in"])(
    "keeps pre-competition data sections discoverable but locked during %s",
    (status) => {
      const items = model(status);
      const locked = items.filter((item) => !item.available);

      expect(locked.map((item) => item.id)).toEqual([
        "bracket",
        "teams",
        "matches",
        "heroes",
        "standings"
      ]);
      expect(items.find((item) => item.id === "participants")?.available).toBe(true);
      expect(items.find((item) => item.id === "draft")?.available).toBe(true);
      expect(locked.every((item) => Boolean(item.reasonKey))).toBe(true);
    }
  );

  it.each<TournamentStatus>(["live", "playoffs", "completed", "archived"])(
    "unlocks competition sections during %s when a stage exists",
    (status) => {
      expect(model(status).every((item) => item.available)).toBe(true);
    }
  );

  it("locks only the bracket for missing stage structure after competition starts", () => {
    const items = model("live", `/tournaments/${tournamentId}/bracket`, []);
    const bracket = items.find((item) => item.id === "bracket");

    expect(bracket).toMatchObject({
      available: false,
      active: true,
      reasonKey: "tournamentDetail.nav.reasons.noStages",
      href: `/tournaments/${tournamentId}/bracket`
    });
    expect(items.filter((item) => item.id !== "bracket").every((item) => item.available)).toBe(
      true
    );
  });

  it("prefers the active stage, then elimination, then group stage for the bracket href", () => {
    const stages = [
      stage({ id: 1, stage_type: "round_robin", is_active: false }),
      stage({ id: 2, stage_type: "double_elimination", is_active: false }),
      stage({ id: 3, stage_type: "swiss", is_active: true })
    ];

    expect(model("live", undefined, stages).find((item) => item.id === "bracket")?.href).toBe(
      `/tournaments/${tournamentId}/bracket?stage=3`
    );
  });

  it("uses stable ids and label keys and omits Draft for non-draft tournaments", () => {
    const items = buildTournamentSectionNav({
      tournamentId,
      status: "completed",
      stages: [stage()],
      teamFormation: "balancer",
      pathname: `/tournaments/${tournamentId}/teams`
    });

    expect(items.map(({ id, labelKey }) => [id, labelKey])).toEqual([
      ["bracket", "common.bracket"],
      ["teams", "common.teams"],
      ["participants", "common.participants"],
      ["matches", "common.matches"],
      ["heroes", "common.heroes"],
      ["standings", "common.standings"]
    ]);
  });

  it("links Draft to the standalone room and recognizes that route as active", () => {
    const draft = model("draft", `/draft/${tournamentId}`).find((item) => item.id === "draft");

    expect(draft).toMatchObject({
      href: `/draft/${tournamentId}`,
      active: true,
      available: true
    });
  });

  it("marks exactly the canonical nested route active", () => {
    const items = model("playoffs", `/tournaments/${tournamentId}/standings/`);

    expect(items.filter((item) => item.active).map((item) => item.id)).toEqual(["standings"]);
  });
});

describe("getTournamentPhaseNoteKey", () => {
  it.each<TournamentStatus>([
    "registration",
    "draft",
    "check_in",
    "live",
    "playoffs",
    "completed",
    "archived"
  ])("returns a localized phase note key for %s", (status) => {
    expect(getTournamentPhaseNoteKey(status, true)).toBe(`tournamentDetail.nav.phase.${status}`);
  });

  it("explains missing stage structure after the competition begins", () => {
    expect(getTournamentPhaseNoteKey("live", false)).toBe(
      "tournamentDetail.nav.phase.awaitingStages"
    );
  });
});
