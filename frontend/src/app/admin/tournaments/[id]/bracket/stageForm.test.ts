import { describe, expect, it } from "vitest";

import type { Stage } from "@/types/tournament.types";

import { buildStageUpdatePayload, stageFormChanges, stageFormFromStage } from "./stageForm";

function stage(overrides: Partial<Stage> = {}): Stage {
  return {
    id: 1,
    tournament_id: 84,
    name: "Swiss day",
    description: null,
    stage_type: "individual_swiss",
    max_rounds: 5,
    advance_count: null,
    advance_upper_count: null,
    pairing_mode: "score",
    playoff_team_count: 4,
    order: 1,
    is_active: false,
    is_published: false,
    is_completed: false,
    has_custom_bracket: false,
    challonge_id: null,
    challonge_slug: null,
    ranking_preset: null,
    tiebreak_order: null,
    scoring: { win: null, draw: null, loss: null, preset: null, columns: null, placement_points: null, formula: null },
    swiss_bye_points: null,
    swiss_qualify_wins: null,
    swiss_eliminate_losses: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 3, by_round: {}, final: null, swiss_qualify: null, swiss_eliminate: null },
    items: [],
    ...overrides
  };
}

describe("stage form for an individual Swiss stage", () => {
  it("round-trips the saved pairing mode and playoff team count", () => {
    const saved = stage({ pairing_mode: "balance", playoff_team_count: 8 });
    const form = stageFormFromStage(saved);
    expect(form).toMatchObject({ pairingMode: "balance", playoffTeamCount: 8 });
    expect(stageFormChanges(saved, form)).toEqual([]);
  });

  it("sends both settings, with the rounds, for an individual Swiss stage", () => {
    const saved = stage();
    const payload = buildStageUpdatePayload(saved, {
      ...stageFormFromStage(saved),
      maxRounds: "7",
      pairingMode: "balance",
      playoffTeamCount: 2
    });
    expect(payload).toMatchObject({ max_rounds: 7, pairing_mode: "balance", playoff_team_count: 2 });
  });

  it("names the edited setting in the save summary", () => {
    const saved = stage();
    const form = { ...stageFormFromStage(saved), playoffTeamCount: 6 };
    expect(stageFormChanges(saved, form)).toEqual(["playoffTeams"]);
  });

  it("sends neither setting for any other stage type", () => {
    const saved = stage({ stage_type: "swiss", pairing_mode: null, playoff_team_count: null });
    const payload = buildStageUpdatePayload(saved, stageFormFromStage(saved));
    expect(payload).not.toHaveProperty("pairing_mode");
    expect(payload).not.toHaveProperty("playoff_team_count");
  });

  it("defaults a legacy stage to score pairing and four playoff teams", () => {
    const form = stageFormFromStage(stage({ pairing_mode: null, playoff_team_count: null }));
    expect(form).toMatchObject({ pairingMode: "score", playoffTeamCount: 4 });
  });
});
