import { describe, expect, it } from "vitest";

import type { TournamentReadiness } from "@/types/admin.types";
import type { TournamentStatus } from "@/types/tournament.types";

import { createTranslator } from "next-intl";

import en from "@/i18n/messages/en.json";

import {
  buildChecklist,
  pickNextAction,
  type ChecklistContext,
  type ChecklistItem,
  type ChecklistTranslator
} from "./tournament-checklist";

const t = createTranslator({ locale: "en", messages: en, namespace: "adminTournaments.checklist" }) as ChecklistTranslator;

function readiness(overrides: Partial<TournamentReadiness> = {}): TournamentReadiness {
  return {
    tournament_id: 7,
    status: "live",
    formation_modes: ["balancer"],
    schedule_configured: true,
    grid_selected: true,
    stages_total: 2,
    stage_slots_filled: true,
    bracket_generated: true,
    duel_encounters_total: 10,
    duel_encounters_with_logs: 0,
    logs_used: false,
    standings_recalc_pending: false,
    registration_form_configured: true,
    registrations_pending: 1,
    registrations_approved: 3,
    registrations_checked_in: 2,
    registrations_ranked: 3,
    pool_ready: 3,
    pool_need_fix: 0,
    balance_saved: false,
    balance_exported_at: null,
    draft_session_status: null,
    results_overdue: 0,
    results_pending_confirmation: 0,
    results_disputed: 0,
    achievements_status: "done",
    ...overrides
  };
}

/** team.read group fully masked by the backend (D16). */
const TEAM_MASKED: Partial<TournamentReadiness> = {
  registration_form_configured: null,
  registrations_pending: null,
  registrations_approved: null,
  registrations_checked_in: null,
  registrations_ranked: null,
  pool_ready: null,
  pool_need_fix: null,
  balance_saved: null,
  balance_exported_at: null,
  draft_session_status: null
};

/** tournament.read group fully masked by the backend (D16). */
const SETUP_MASKED: Partial<TournamentReadiness> = {
  schedule_configured: null,
  grid_selected: null,
  stages_total: null,
  stage_slots_filled: null,
  bracket_generated: null,
  duel_encounters_total: null,
  duel_encounters_with_logs: null,
  logs_used: null,
  standings_recalc_pending: null
};

function ctx(overrides: Partial<ChecklistContext> = {}): ChecklistContext {
  return {
    basePath: "/admin/tournaments/7",
    status: "live",
    hasChallongeSource: false,
    ...overrides
  };
}

function at(status: TournamentStatus, overrides: Partial<TournamentReadiness> = {}): ChecklistItem[] {
  return buildChecklist(readiness(overrides), ctx({ status }), t);
}

function byKey(items: ChecklistItem[], key: string): ChecklistItem {
  const item = items.find((candidate) => candidate.key === key);
  if (!item) throw new Error(`checklist item "${key}" not found`);
  return item;
}

const keys = (items: ChecklistItem[]) => items.map((item) => item.key);

describe("buildChecklist", () => {
  it("a completed tournament asks only about results, logs and wrap-up", () => {
    // The reported bug: "Registration open" and check-in nagged after the event.
    expect(keys(at("completed"))).toEqual(["results", "logs", "achievements", "standings"]);
  });

  it("an archived tournament has nothing left to check", () => {
    expect(at("archived", { logs_used: true, duel_encounters_with_logs: 3 })).toEqual([]);
  });

  it("each status shows only the items whose window it is in", () => {
    expect(keys(at("announcement"))).toEqual(["schedule", "grid", "registration_form", "stages"]);
    expect(keys(at("live"))).toEqual([
      "schedule",
      "grid",
      "registration_form",
      "registrations_reviewed",
      "ranks",
      "check_in",
      "pool_ready",
      "balance_saved",
      "balance_exported",
      "stages",
      "slots",
      "bracket",
      "results",
      "logs"
    ]);
  });

  it("check-in is progress, never open work", () => {
    const checkIn = byKey(at("live"), "check_in");
    expect(checkIn.state).toBe("info");
    expect(checkIn.detail).toBe("2/3 checked in");
    expect(byKey(at("live", TEAM_MASKED), "check_in").state).toBe("no-access");
  });

  it("pending registrations need review", () => {
    expect(byKey(at("live", { registrations_pending: 2 }), "registrations_reviewed").state).toBe("warn");
    expect(byKey(at("live", { registrations_pending: 0 }), "registrations_reviewed").state).toBe("done");
  });

  it("masked groups render no-access instead of zeros", () => {
    const team = at("live", TEAM_MASKED);
    for (const key of ["registration_form", "registrations_reviewed", "ranks", "pool_ready", "balance_saved", "balance_exported"]) {
      expect(byKey(team, key).state, key).toBe("no-access");
    }
    const setup = at("live", SETUP_MASKED);
    for (const key of ["schedule", "grid", "stages"]) {
      expect(byKey(setup, key).state, key).toBe("no-access");
    }
    const finished = at("completed", { ...SETUP_MASKED, results_disputed: null, achievements_status: null });
    for (const key of ["results", "logs", "achievements", "standings"]) {
      expect(byKey(finished, key).state, key).toBe("no-access");
    }
  });

  it("results warn on disputes, pending confirmations and — only while play goes on — overdue matches", () => {
    const live = byKey(at("live", { results_disputed: 1, results_overdue: 2 }), "results");
    expect(live.state).toBe("warn");
    expect(live.detail).toBe("1 disputed · 2 overdue");

    expect(byKey(at("completed", { results_overdue: 4 }), "results").state).toBe("done");
    expect(byKey(at("completed", { results_pending_confirmation: 1 }), "results").state).toBe("warn");
  });

  it("missing logs are progress during play and a to-do once completed", () => {
    const partial = { logs_used: true, duel_encounters_with_logs: 4, duel_encounters_total: 10 };
    expect(byKey(at("live", partial), "logs").state).toBe("info");
    expect(byKey(at("completed", partial), "logs").state).toBe("todo");
    expect(byKey(at("completed", partial), "logs").detail).toBe("4/10 matches with logs");

    const full = { logs_used: true, duel_encounters_with_logs: 10, duel_encounters_total: 10 };
    expect(byKey(at("completed", full), "logs").state).toBe("done");

    const notUsed = byKey(at("completed", { logs_used: false }), "logs");
    expect(notUsed.state).toBe("skipped");
    expect(notUsed.detail).toBe("Logs: not used");
  });

  it("achievements follow the latest evaluation run", () => {
    const state = (achievements_status: string) =>
      byKey(at("completed", { achievements_status }), "achievements").state;
    expect(state("done")).toBe("done");
    expect(state("not_configured")).toBe("skipped");
    expect(state("none")).toBe("todo");
    expect(state("running")).toBe("todo");
    expect(state("partial")).toBe("warn");
    expect(state("failed")).toBe("warn");
  });

  it("standings wait for a queued recalculation", () => {
    expect(byKey(at("completed", { standings_recalc_pending: true }), "standings").state).toBe("todo");
    expect(byKey(at("completed"), "standings").state).toBe("done");
  });

  it("formation items follow the formation modes", () => {
    const balancer = keys(at("live", { formation_modes: ["balancer"] }));
    expect(balancer).toEqual(expect.arrayContaining(["pool_ready", "balance_saved", "balance_exported"]));
    expect(balancer).not.toContain("draft_completed");

    const draft = at("live", { formation_modes: ["draft"], draft_session_status: "completed" });
    expect(keys(draft)).not.toContain("pool_ready");
    expect(byKey(draft, "draft_completed").state).toBe("done");

    const draftPending = byKey(at("live", { formation_modes: ["draft"], draft_session_status: "live" }), "draft_completed");
    expect(draftPending.state).toBe("todo");
    // The session status is translated, never the raw enum, and the row leads to the board.
    expect(draftPending.detail).toBe("Draft is live");
    expect(draftPending.href).toBe("/admin/tournaments/7/teams/draft");
  });

  it("pool warns when registrations need fixing", () => {
    expect(byKey(at("live", { pool_ready: 5, pool_need_fix: 2 }), "pool_ready").state).toBe("warn");
  });

  it("registration form hidden for challonge-sourced tournaments", () => {
    const items = buildChecklist(readiness(), ctx({ hasChallongeSource: true }), t);
    expect(keys(items)).not.toContain("registration_form");
  });

  it("hrefs point at final tab addresses (D20)", () => {
    expect(byKey(at("live"), "registrations_reviewed").href).toBe("/admin/tournaments/7/registration/entries");
    expect(byKey(at("live"), "pool_ready").href).toBe("/admin/tournaments/7/teams/roster");
    expect(byKey(at("live"), "stages").href).toBe("/admin/tournaments/7/bracket");
    expect(byKey(at("completed"), "results").href).toBe("/admin/tournaments/7/matches/encounters");
    expect(byKey(at("completed"), "logs").href).toBe("/admin/tournaments/7/matches/logs");
  });
});

describe("pickNextAction", () => {
  it("prefers a warning over an earlier to-do", () => {
    const items = at("live", { grid_selected: false, registrations_pending: 3 });
    expect(pickNextAction(items)?.key).toBe("registrations_reviewed");
  });

  it("falls back to the first to-do, and to nothing when all is done", () => {
    expect(pickNextAction(at("live", { grid_selected: false, registrations_pending: 0 }))?.key).toBe("grid");
    expect(pickNextAction(at("completed"))).toBeUndefined();
  });

  it("never points a completed tournament back at registration", () => {
    const items = at("completed", { logs_used: true, duel_encounters_with_logs: 72, duel_encounters_total: 79 });
    expect(pickNextAction(items)?.key).toBe("logs");
  });
});
