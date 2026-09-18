import { describe, expect, it } from "vitest";

import type { PhaseScheduleFormState, TournamentFormState } from "./tournamentWorkspace.helpers";
import { getTournamentUpdatePayload } from "./tournamentWorkspace.helpers";

const EMPTY_SCHEDULE: PhaseScheduleFormState = {
  registration: { starts_at: "", ends_at: "" },
  check_in: { starts_at: "", ends_at: "" },
  draft: { starts_at: "", ends_at: "" },
  live: { starts_at: "", ends_at: "" }
};

function form(partial: Partial<TournamentFormState> = {}): TournamentFormState {
  return {
    name: "OWT 64",
    description: "",
    rules: "",
    challonge_slug: "owt-64",
    slug: "owt-64",
    is_league: false,
    is_finished: false,
    is_hidden: false,
    start_date: "2026-04-18",
    end_date: "2026-04-19",
    win_points: 3,
    draw_points: 1,
    loss_points: 0,
    auto_transitions_enabled: true,
    allow_late_registration: false,
    phase_schedule: EMPTY_SCHEDULE,
    division_grid_version_id: null,
    team_formation: "balancer",
    roster_slots_json: null,
    ...partial
  };
}

describe("getTournamentUpdatePayload", () => {
  it("sends nothing when the form was never touched", () => {
    const initial = form();
    expect(getTournamentUpdatePayload(initial, initial)).toEqual({});
  });

  it("sends only the field the admin actually changed", () => {
    const initial = form();
    const current = form({ is_finished: true });

    expect(getTournamentUpdatePayload(current, initial)).toEqual({ is_finished: true });
  });

  it("does not flag re-typing the same value, after transforms, as a change", () => {
    const initial = form({ name: "OWT 64", description: "", challonge_slug: "owt-64" });
    // Trailing whitespace and a full Challonge URL normalize back to the
    // stored values -- these must not appear in the diff, or every save would
    // still "change" fields the admin never meant to touch.
    const current = form({
      name: "OWT 64  ",
      description: "   ",
      challonge_slug: "https://challonge.com/owt-64"
    });

    expect(getTournamentUpdatePayload(current, initial)).toEqual({});
  });

  it("diffs roster_slots_json by value, not by reference", () => {
    const initial = form({ roster_slots_json: { tank: 1, damage: 2, support: 2 } });
    const unchanged = form({ roster_slots_json: { tank: 1, damage: 2, support: 2 } });
    const changed = form({ roster_slots_json: { tank: 2, damage: 2, support: 1 } });

    expect(getTournamentUpdatePayload(unchanged, initial)).toEqual({});
    expect(getTournamentUpdatePayload(changed, initial)).toEqual({
      roster_slots_json: { tank: 2, damage: 2, support: 1 }
    });
  });

  it("diffs slug by trimmed value; re-sending the same slug is not a change", () => {
    const initial = form({ slug: "owt-64" });
    const renamed = form({ slug: "owt-64-finals" });
    const retyped = form({ slug: "  owt-64  " });

    expect(getTournamentUpdatePayload(renamed, initial)).toEqual({ slug: "owt-64-finals" });
    expect(getTournamentUpdatePayload(retyped, initial)).toEqual({});
  });

  it("combines every changed field, leaving untouched ones out entirely", () => {
    const initial = form();
    const current = form({ win_points: 1, is_hidden: true });

    expect(getTournamentUpdatePayload(current, initial)).toEqual({
      win_points: 1,
      is_hidden: true
    });
  });

  it("treats a blanked rules document as an explicit unpublish", () => {
    const initial = form({ rules: "## Format\n\nBest of 3." });

    // `null`, not `""`: the column is nullable and the public Rules tab keys
    // its own existence off that, so an empty string would publish a document
    // with nothing in it.
    expect(getTournamentUpdatePayload(form({ rules: "   " }), initial)).toEqual({ rules: null });
    expect(getTournamentUpdatePayload(form({ rules: "## Format\n\nBest of 3." }), initial)).toEqual(
      {}
    );
  });
});
