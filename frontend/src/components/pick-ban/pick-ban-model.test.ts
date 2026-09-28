import { describe, expect, it } from "vitest";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import type {
  PickBanEntry,
  PickBanGame,
  PickBanResolvedStep,
  PickBanSession,
  PickBanState,
  PickBanSubmission,
  VetoUnavailableReason
} from "@/types/tournament.types";

import {
  PICK_BAN_UNAVAILABLE_COPY,
  acceptedScore,
  appliedItemsBySide,
  bannedEntries,
  carriedBanEntries,
  duplicateItemIds,
  eligibleItemIds,
  gameAtPosition,
  groupItemsByRole,
  isSessionActive,
  lastRevealedBlindStep,
  lobbyCopyText,
  pickBanReserveMap,
  pickedItemsInOrder,
  poolRoundGroups,
  remainingEntries,
  roundState,
  seriesMatchesByPosition,
  statusLabelKey,
  stepDeadlineMs,
  stepRoundGroups,
  stepSubmissions,
  stepSummary,
  tileStatus,
  viewerDraftItems
} from "./pick-ban-model";

function game(overrides: Partial<PickBanGame> & { position: number }): PickBanGame {
  return {
    id: overrides.position,
    map_id: 21,
    state: "awaiting_result",
    accepted_home_score: null,
    accepted_away_score: null,
    result_source: null,
    result_version: 1,
    confirmed_at: null,
    reports: [],
    ...overrides
  };
}

function entry(overrides: Partial<PickBanEntry>): PickBanEntry {
  return {
    id: 1,
    item_id: 1,
    round: null,
    order: 0,
    action_index: null,
    picked_by: null,
    protected_by: null,
    team_id: null,
    status: "available",
    carried_from_round: null,
    ...overrides
  };
}

function step(overrides: Partial<PickBanResolvedStep> & { index: number }): PickBanResolvedStep {
  return {
    round: 1,
    phase_id: "main",
    step_id: `s${overrides.index}`,
    action: "ban",
    sides: ["home"],
    count: 1,
    min: 1,
    blind: false,
    target: null,
    lifetime: 1,
    timer_seconds: null,
    on_timeout: "random_fill",
    dispute: { enabled: false, max: 0 },
    eligible: {},
    constraints: [],
    ...overrides
  };
}

function submission(
  overrides: Partial<PickBanSubmission> & { step_index: number; side: PickBanSubmission["side"] }
): PickBanSubmission {
  return {
    attempt: 1,
    state: "revealed",
    items: [],
    ...overrides
  };
}

function session(overrides: Partial<PickBanSession> = {}): PickBanSession {
  return {
    id: 1,
    kind: "map",
    status: "active",
    first_side: "home",
    awaiting_choice: false,
    pending_loser_side: null,
    seed_source: "bracket_slot",
    home_seed: 1,
    away_seed: 2,
    slot_reserves: null,
    started_at: "2026-07-18T10:00:00Z",
    current_step_started_at: "2026-07-18T10:00:00Z",
    ...overrides
  };
}

function state(overrides: Partial<PickBanState>): PickBanState {
  return {
    session: session(),
    readiness: { home: true, away: true },
    sequence: [],
    pool: [],
    submissions: [],
    viewer_side: "home",
    viewer_can_act: false,
    allowed_actions: [],
    current_step_index: null,
    current_step: null,
    expected_action: null,
    acting_sides: [],
    step_progress: null,
    step_deadline: "2026-07-18T10:01:00Z",
    current_round: null,
    is_complete: false,
    eligible: null,
    draft_issues: [],
    targets: null,
    dispute: { available: false, step_index: null, attempts_used: 0, max: 0 },
    undo: { requested_by: null, step_index: null, item_ids: [], action: null, side: null },
    ...overrides
  };
}

describe("stepSummary", () => {
  it("reduces a simultaneous blind per-player ban to what its label needs", () => {
    expect(
      stepSummary(
        step({
          index: 0,
          action: "ban",
          sides: ["home", "away"],
          count: 5,
          blind: true,
          target: "opponent_player",
          lifetime: 2
        })
      )
    ).toEqual({
      action: "ban",
      sides: ["home", "away"],
      system: false,
      count: 5,
      blind: true,
      targeted: true,
      lifetime: 2
    });
  });

  it("omits the parameters that add nothing: a single item and a one-map ban", () => {
    const summary = stepSummary(step({ index: 1, count: 1, lifetime: 1 }));
    expect(summary.count).toBeNull();
    expect(summary.lifetime).toBeNull();
    expect(summary.targeted).toBe(false);
  });

  it("marks a ban that outlives the series as such, never as 'no lifetime'", () => {
    // `null` on the wire means "rest of the series" — the exact opposite of
    // "nothing to say", so it cannot collapse into the same omitted chip.
    expect(stepSummary(step({ index: 2, action: "ban", lifetime: null })).lifetime).toBe("series");
    // A pick has no lifetime concept at all.
    expect(stepSummary(step({ index: 3, action: "pick", lifetime: null })).lifetime).toBeNull();
  });

  it("reads an engine-resolved step as system, with no acting side", () => {
    const summary = stepSummary(step({ index: 4, action: "decider", sides: ["system"] }));
    expect(summary.system).toBe(true);
    expect(summary.sides).toEqual([]);
  });
});

describe("stepRoundGroups", () => {
  it("groups the resolved steps by the round each one belongs to", () => {
    const sequence = [
      step({ index: 0, round: 1 }),
      step({ index: 1, round: 1, sides: ["home", "away"], count: 2, blind: true }),
      step({ index: 2, round: 2 }),
      step({ index: 3, round: 2 })
    ];
    expect(
      stepRoundGroups(sequence)?.map(({ round, steps }) => ({
        round,
        indices: steps.map((resolved) => resolved.index)
      }))
    ).toEqual([
      { round: 1, indices: [0, 1] },
      { round: 2, indices: [2, 3] }
    ]);
  });

  it("returns null for a flat (round-less) sequence", () => {
    expect(stepRoundGroups([step({ index: 0, round: null })])).toBeNull();
  });
});

describe("stepDeadlineMs", () => {
  it("parses the server's deadline rather than adding a timer to a start time", () => {
    expect(stepDeadlineMs(state({}))).toBe(Date.parse("2026-07-18T10:01:00Z"));
  });

  it("shows no countdown without a deadline, or once the room is closed", () => {
    expect(stepDeadlineMs(state({ step_deadline: null }))).toBeNull();
    expect(stepDeadlineMs(state({ is_complete: true }))).toBeNull();
    expect(stepDeadlineMs(state({ session: session({ status: "completed" }) }))).toBeNull();
    expect(stepDeadlineMs(state({ session: null }))).toBeNull();
  });
});

describe("stepSubmissions", () => {
  it("keeps only the current attempt, so a disputed step shows its redo", () => {
    const submissions = [
      submission({ step_index: 0, side: "home", attempt: 1, items: [{ item_id: 1, target_player_id: null }] }),
      submission({ step_index: 0, side: "home", attempt: 2, state: "draft", items: [] }),
      submission({ step_index: 1, side: "away", items: [] })
    ];
    const rows = stepSubmissions(submissions, 0);
    expect(rows).toHaveLength(1);
    expect(rows[0].attempt).toBe(2);
  });
});

describe("viewerDraftItems", () => {
  it("is the viewer's own submission on the step in play", () => {
    const items = viewerDraftItems(
      state({
        current_step_index: 3,
        viewer_side: "away",
        submissions: [
          submission({ step_index: 3, side: "home", state: "draft", items: [{ item_id: 9, target_player_id: null }] }),
          submission({ step_index: 3, side: "away", state: "draft", items: [{ item_id: 7, target_player_id: 11 }] })
        ]
      })
    );
    expect(items).toEqual([{ item_id: 7, target_player_id: 11 }]);
  });

  it("is empty for a spectator and before anything is drafted", () => {
    expect(viewerDraftItems(state({ current_step_index: 3, viewer_side: null }))).toEqual([]);
    expect(viewerDraftItems(state({ current_step_index: null }))).toEqual([]);
  });
});

describe("duplicateItemIds", () => {
  it("marks what both sides named in the same blind step", () => {
    const duplicates = duplicateItemIds([
      submission({
        step_index: 0,
        side: "home",
        items: [
          { item_id: 1, target_player_id: null },
          { item_id: 2, target_player_id: null }
        ]
      }),
      submission({
        step_index: 0,
        side: "away",
        items: [
          { item_id: 2, target_player_id: null },
          { item_id: 3, target_player_id: null }
        ]
      })
    ]);
    expect([...duplicates]).toEqual([2]);
  });

  it("does not call one side's repeat of an item a duplicate", () => {
    const duplicates = duplicateItemIds([
      submission({
        step_index: 0,
        side: "home",
        items: [
          { item_id: 4, target_player_id: 1 },
          { item_id: 4, target_player_id: 2 }
        ]
      })
    ]);
    expect(duplicates.size).toBe(0);
  });
});

describe("appliedItemsBySide", () => {
  const sequence = [
    step({ index: 0, round: 1, sides: ["home", "away"], count: 2, blind: true }),
    step({ index: 1, round: 2, sides: ["home"], action: "protect" })
  ];

  it("credits a merged duplicate ban to BOTH sides that spent it", () => {
    // The board writes ONE banned entry with one `picked_by`; reading it would
    // leave the other side a ban short of what it actually paid.
    const applied = appliedItemsBySide(
      sequence,
      [
        submission({
          step_index: 0,
          side: "home",
          items: [
            { item_id: 1, target_player_id: null },
            { item_id: 2, target_player_id: null }
          ]
        }),
        submission({
          step_index: 0,
          side: "away",
          items: [
            { item_id: 2, target_player_id: null },
            { item_id: 3, target_player_id: null }
          ]
        })
      ],
      { round: 1 }
    );
    expect(applied.home.map((item) => item.item_id)).toEqual([1, 2]);
    expect(applied.away.map((item) => item.item_id)).toEqual([2, 3]);
  });

  it("hides an unrevealed blind draft, and shows an open step's immediately", () => {
    const blindDraft = appliedItemsBySide(sequence, [
      submission({
        step_index: 0,
        side: "home",
        state: "locked",
        items: [{ item_id: 1, target_player_id: null }]
      })
    ]);
    expect(blindDraft.home).toEqual([]);

    const openDraft = appliedItemsBySide(sequence, [
      submission({
        step_index: 1,
        side: "home",
        state: "draft",
        items: [{ item_id: 5, target_player_id: null }]
      })
    ]);
    expect(openDraft.home.map((item) => item.item_id)).toEqual([5]);
  });

  it("narrows to one round and one action", () => {
    const submissions = [
      submission({ step_index: 0, side: "home", items: [{ item_id: 1, target_player_id: null }] }),
      submission({ step_index: 1, side: "home", items: [{ item_id: 5, target_player_id: null }] })
    ];
    expect(
      appliedItemsBySide(sequence, submissions, { round: 2, action: "protect" }).home.map(
        (item) => item.item_id
      )
    ).toEqual([5]);
    expect(
      appliedItemsBySide(sequence, submissions, { round: 2, action: "ban" }).home
    ).toEqual([]);
  });
});

describe("lastRevealedBlindStep", () => {
  const sequence = [
    step({ index: 0, blind: true, sides: ["home", "away"] }),
    step({ index: 1, blind: true, sides: ["home", "away"] }),
    step({ index: 2, blind: false })
  ];

  it("finds the newest blind step whose drafts are all out", () => {
    const submissions = [
      submission({ step_index: 0, side: "home" }),
      submission({ step_index: 0, side: "away" }),
      submission({ step_index: 1, side: "home" }),
      submission({ step_index: 1, side: "away" })
    ];
    expect(lastRevealedBlindStep(sequence, submissions)?.index).toBe(1);
  });

  it("skips a step still holding a locked draft, and reports none before any reveal", () => {
    const partial = [
      submission({ step_index: 0, side: "home" }),
      submission({ step_index: 0, side: "away" }),
      submission({ step_index: 1, side: "home", state: "locked" })
    ];
    expect(lastRevealedBlindStep(sequence, partial)?.index).toBe(0);
    expect(lastRevealedBlindStep(sequence, [])).toBeNull();
  });
});

describe("eligibleItemIds", () => {
  const eligible = {
    item_ids: [1, 2, 3],
    by_target: { "11": [1, 2], "12": [3] }
  };

  it("is null when the server named nothing — the viewer cannot act", () => {
    expect(eligibleItemIds(null, null)).toBeNull();
  });

  it("is the whole set until a target is chosen, then that player's own", () => {
    expect([...eligibleItemIds(eligible, null)!]).toEqual([1, 2, 3]);
    expect([...eligibleItemIds(eligible, 11)!]).toEqual([1, 2]);
    expect([...eligibleItemIds(eligible, 12)!]).toEqual([3]);
  });

  it("is empty for a player the step allows nothing for", () => {
    expect(eligibleItemIds(eligible, 99)!.size).toBe(0);
  });
});

describe("tileStatus", () => {
  const base = { canSelect: true, currentRound: 1, draftItemIds: new Set<number>() };

  it("greys what the server left out of `eligible`, and keeps the rest clickable", () => {
    const eligibleIds = new Set([1]);
    expect(tileStatus(entry({ item_id: 1, round: 1 }), { ...base, eligibleIds })).toMatchObject({
      selectable: true,
      ineligible: false
    });
    expect(tileStatus(entry({ item_id: 2, round: 1 }), { ...base, eligibleIds })).toMatchObject({
      selectable: false,
      ineligible: true
    });
  });

  it("keeps a drafted item clickable, because that click takes it back out", () => {
    const status = tileStatus(entry({ item_id: 9, round: 1 }), {
      ...base,
      eligibleIds: new Set<number>(),
      draftItemIds: new Set([9])
    });
    expect(status).toMatchObject({ selectable: true, drafted: true, ineligible: false });
  });

  it("never marks an inert tile ineligible: a taken item, a closed round, a spectator", () => {
    const eligibleIds = new Set([1]);
    expect(
      tileStatus(entry({ item_id: 1, round: 1, status: "banned" }), { ...base, eligibleIds })
    ).toMatchObject({ selectable: false, ineligible: false });
    expect(
      tileStatus(entry({ item_id: 1, round: 2 }), { ...base, eligibleIds })
    ).toMatchObject({ selectable: false, ineligible: false, locked: true });
    expect(
      tileStatus(entry({ item_id: 1, round: 1 }), { ...base, canSelect: false, eligibleIds })
    ).toMatchObject({ selectable: false, ineligible: false });
  });
});

describe("carried, banned and remaining entries", () => {
  const pool = [
    entry({ id: 1, item_id: 101, round: 2, status: "banned", carried_from_round: 1, picked_by: "home" }),
    entry({ id: 2, item_id: 102, round: 2, status: "banned", picked_by: "away" }),
    entry({ id: 3, item_id: 103, round: 2, status: "available" }),
    entry({ id: 4, item_id: 104, round: 2, status: "protected", protected_by: "home" }),
    entry({ id: 5, item_id: 105, round: 1, status: "banned", picked_by: "home" })
  ];

  it("separates the bans carried in from the ones spent on this map", () => {
    expect(carriedBanEntries(pool, 2).map((e) => e.item_id)).toEqual([101]);
    expect(carriedBanEntries(pool, 1)).toEqual([]);
  });

  it("counts a carried ban as unavailable on this map, like any other", () => {
    expect(bannedEntries(pool, 2).map((e) => e.item_id)).toEqual([101, 102]);
  });

  it("leaves a PROTECTED entry in what the map still has — a protect keeps it playable", () => {
    expect(remainingEntries(pool, 2).map((e) => e.item_id)).toEqual([103, 104]);
  });

  it("treats a flat pool's entries as belonging to every round", () => {
    const flat = [entry({ item_id: 7, round: null, status: "banned" })];
    expect(bannedEntries(flat, 3).map((e) => e.item_id)).toEqual([7]);
    expect(bannedEntries(flat, null).map((e) => e.item_id)).toEqual([7]);
  });
});

describe("groupItemsByRole / lobbyCopyText", () => {
  const items = [
    { itemId: 1, name: "Zarya", role: "tank" as const },
    { itemId: 2, name: "Ana", role: "support" as const },
    { itemId: 3, name: "Ashe", role: "damage" as const },
    { itemId: 4, name: "Reinhardt", role: "tank" as const },
    { itemId: 5, name: "Unknown", role: null }
  ];

  it("orders tank-damage-support with the unknown bucket last, names sorted", () => {
    expect(
      groupItemsByRole(items).map((group) => [group.role, group.items.map((item) => item.name)])
    ).toEqual([
      ["tank", ["Reinhardt", "Zarya"]],
      ["damage", ["Ashe"]],
      ["support", ["Ana"]],
      [null, ["Unknown"]]
    ]);
  });

  it("writes one line per role, which is how the lobby's hero list is grouped", () => {
    expect(lobbyCopyText(groupItemsByRole(items.slice(0, 3)), (role) => role ?? "other")).toBe(
      "tank: Zarya\ndamage: Ashe\nsupport: Ana"
    );
  });
});

describe("pickedItemsInOrder", () => {
  it("keeps picked items sorted by global action order", () => {
    const pool = [
      entry({ id: 1, item_id: 11, status: "banned", action_index: 0 }),
      entry({ id: 2, item_id: 12, status: "picked", action_index: 2 }),
      entry({ id: 3, item_id: 13, status: "picked", action_index: 1 }),
      entry({ id: 4, item_id: 14, status: "available" })
    ];
    expect(pickedItemsInOrder(pool).map((e) => e.item_id)).toEqual([13, 12]);
  });

  it("falls back to `order` when action_index is unset", () => {
    const pool = [
      entry({ id: 1, item_id: 11, status: "picked", order: 2 }),
      entry({ id: 2, item_id: 12, status: "picked", order: 1 })
    ];
    expect(pickedItemsInOrder(pool).map((e) => e.item_id)).toEqual([12, 11]);
  });
});

describe("seriesMatchesByPosition", () => {
  /** A `Match` row reduced to what the series strip reads, plus a tag to assert on. */
  const row = (map_id: number, map_index: number | null, tag: string) => ({
    map_id,
    map_index,
    tag
  });

  it("gives each play of a repeated map its own row", () => {
    const rows = [row(21, 1, "first"), row(21, 2, "second")];
    expect(seriesMatchesByPosition(rows, [21, 21]).map((match) => match?.tag)).toEqual([
      "first",
      "second"
    ]);
  });

  it("ignores a row whose position belongs to another map", () => {
    const rows = [row(21, 1, "first"), row(22, 2, "other")];
    expect(seriesMatchesByPosition(rows, [21, 21]).map((match) => match?.tag)).toEqual([
      "first",
      undefined
    ]);
  });

  it("adopts a positionless row for the earliest play that has no exact one", () => {
    // A parsed log carries no position, and neither does any row written before
    // `Match.map_index` existed: the second play HAS its own row, so the
    // positionless one belongs to the first.
    const rows = [row(21, null, "log"), row(21, 2, "second")];
    expect(seriesMatchesByPosition(rows, [21, 21]).map((match) => match?.tag)).toEqual([
      "log",
      "second"
    ]);
  });

  it("never hands one row to two positions", () => {
    const rows = [row(21, null, "log")];
    expect(seriesMatchesByPosition(rows, [21, 21]).map((match) => match?.tag)).toEqual([
      "log",
      undefined
    ]);
  });
});

describe("gameAtPosition", () => {
  it("finds the game by position, whatever order the payload lists them in", () => {
    const games = [game({ position: 2 }), game({ position: 1 })];
    expect(gameAtPosition(games, 1)?.position).toBe(1);
    expect(gameAtPosition(games, 2)?.position).toBe(2);
  });

  it("keys on the position, never the map a series plays twice", () => {
    // Both positions ran map 21; keyed on the map alone the third play would
    // inherit the first play's confirmed result.
    const games = [
      game({ position: 1, map_id: 21, state: "confirmed", accepted_home_score: 2, accepted_away_score: 1 }),
      game({ position: 2, map_id: 21 })
    ];
    expect(acceptedScore(gameAtPosition(games, 2))).toBeNull();
  });

  it("has no game for a position the server has not opened", () => {
    expect(gameAtPosition([game({ position: 1 })], 3)).toBeNull();
  });
});

describe("acceptedScore", () => {
  it("returns the accepted score of a confirmed game", () => {
    expect(
      acceptedScore(
        game({ position: 1, state: "confirmed", accepted_home_score: 2, accepted_away_score: 1 })
      )
    ).toEqual({ home: 2, away: 1 });
  });

  it("shows nothing while a single claim stands", () => {
    expect(
      acceptedScore(
        game({
          position: 1,
          state: "awaiting_result",
          reports: [{ side: "home", home_score: 2, away_score: 1 }]
        })
      )
    ).toBeNull();
  });

  it("shows nothing on a dispute", () => {
    // The server refuses to advance the series here too, so there is no score
    // yet to print — showing either claim would invent one.
    expect(
      acceptedScore(
        game({
          position: 1,
          state: "disputed",
          reports: [
            { side: "home", home_score: 2, away_score: 1 },
            { side: "away", home_score: 0, away_score: 2 }
          ]
        })
      )
    ).toBeNull();
  });

  it("shows nothing for a cancelled game that still carries its old numbers", () => {
    expect(
      acceptedScore(
        game({ position: 1, state: "cancelled", accepted_home_score: 2, accepted_away_score: 1 })
      )
    ).toBeNull();
  });

  it("has nothing to show without a game", () => {
    expect(acceptedScore(null)).toBeNull();
  });
});

describe("isSessionActive", () => {
  it("is true only for a non-null active session", () => {
    expect(isSessionActive(session({ status: "active" }))).toBe(true);
    expect(isSessionActive(session({ status: "completed" }))).toBe(false);
    expect(isSessionActive(session({ status: "cancelled" }))).toBe(false);
    expect(isSessionActive(null)).toBe(false);
  });
});

/**
 * Resolve a dotted key under `pickBan.room`, the namespace every copy key in
 * `PICK_BAN_UNAVAILABLE_COPY` and the round timeline/grid copy is relative to.
 */
function roomMessage(catalogue: typeof en | typeof ru, key: string): unknown {
  return key
    .split(".")
    .reduce<unknown>(
      (node, segment) =>
        node != null && typeof node === "object"
          ? (node as Record<string, unknown>)[segment]
          : undefined,
      catalogue.pickBan.room
    );
}

describe("PICK_BAN_UNAVAILABLE_COPY", () => {
  const REASONS: readonly VetoUnavailableReason[] = [
    "not_configured",
    "teams_unknown",
    "slot_count_mismatch",
    "slot_underfilled",
    "not_ready",
    "waiting_map",
    "bracket_preview"
  ];

  it("covers exactly the reasons the union carries", () => {
    expect(new Set(Object.keys(PICK_BAN_UNAVAILABLE_COPY))).toEqual(new Set(REASONS));
  });

  it("gives every mapped reason its own non-empty copy in both locales", () => {
    const entries = Object.entries(PICK_BAN_UNAVAILABLE_COPY);
    const seen: Record<"titleKey" | "hintKey" | "en" | "ru", Set<string>> = {
      titleKey: new Set(),
      hintKey: new Set(),
      en: new Set(),
      ru: new Set()
    };
    for (const [reason, { titleKey, hintKey }] of entries) {
      seen.titleKey.add(titleKey);
      seen.hintKey.add(hintKey);
      for (const [locale, catalogue] of [
        ["en", en],
        ["ru", ru]
      ] as const) {
        for (const key of [titleKey, hintKey]) {
          const message = roomMessage(catalogue, key);
          expect(message, `${locale}: ${reason} -> ${key}`).toBeTypeOf("string");
          expect(message as string, `${locale}: ${reason} -> ${key}`).not.toBe("");
          seen[locale].add(message as string);
        }
      }
    }
    expect(seen.titleKey.size).toBe(entries.length);
    expect(seen.hintKey.size).toBe(entries.length);
    expect(seen.en.size).toBe(entries.length * 2);
    expect(seen.ru.size).toBe(entries.length * 2);
  });
});

/**
 * A three-round Bo5 whose numbers all disagree with one another, so no helper
 * can pass by confusing round/order/id.
 *
 * Round 1 has resolved (one survivor, two bans), round 2 is mid-ban, round 3
 * has not opened yet.
 */
function roundPool(): PickBanEntry[] {
  return [
    entry({ id: 71, item_id: 41, round: 3, order: 6, status: "available" }),
    entry({ id: 62, item_id: 33, round: 2, order: 4, status: "available" }),
    entry({
      id: 53,
      item_id: 21,
      round: 1,
      order: 1,
      status: "picked",
      picked_by: "decider",
      action_index: 2
    }),
    entry({ id: 74, item_id: 42, round: 3, order: 7, status: "available" }),
    entry({ id: 51, item_id: 22, round: 1, order: 2, status: "banned", action_index: 0 }),
    entry({ id: 75, item_id: 43, round: 3, order: 8, status: "available" }),
    entry({ id: 61, item_id: 32, round: 2, order: 3, status: "banned", action_index: 3 }),
    entry({ id: 52, item_id: 23, round: 1, order: 5, status: "banned", action_index: 1 }),
    entry({ id: 76, item_id: 44, round: 3, order: 9, status: "available" })
  ];
}

describe("poolRoundGroups", () => {
  it("groups by round in ascending play order", () => {
    expect(poolRoundGroups(roundPool())?.map((group) => group.round)).toEqual([1, 2, 3]);
  });

  it("returns null for a flat (round-less) pool", () => {
    expect(poolRoundGroups([entry({ round: null })])).toBeNull();
  });
});

describe("roundState", () => {
  const groups = poolRoundGroups(roundPool()) ?? [];

  it("separates resolved, current and not-yet-open rounds", () => {
    expect(roundState(groups[0], 2)).toBe("resolved");
    expect(roundState(groups[1], 2)).toBe("current");
    expect(roundState(groups[2], 2)).toBe("upcoming");
  });

  it("calls every round resolved once the sequence is complete", () => {
    // A completed round-mode session reports `current_round: null`, exactly
    // like a flat one, so nothing may be inferred from the null itself.
    const finished = poolRoundGroups(
      roundPool().map((e) => (e.status === "available" ? { ...e, status: "banned" as const } : e))
    );
    expect(finished?.map((group) => roundState(group, null))).toEqual([
      "resolved",
      "resolved",
      "resolved"
    ]);
  });
});

describe("statusLabelKey", () => {
  it("calls a round survivor remaining, not picked", () => {
    const survivor = entry({ round: 1, status: "picked", picked_by: "decider" });
    expect(statusLabelKey(survivor)).toBe("status.remaining");
  });

  it("keeps a flat-mode trailing decider as picked", () => {
    const decider = entry({ round: null, status: "picked", picked_by: "decider" });
    expect(statusLabelKey(decider)).toBe("status.picked");
  });

  it("otherwise labels by the entry's own status", () => {
    expect(statusLabelKey(entry({ status: "available" }))).toBe("status.available");
    expect(statusLabelKey(entry({ status: "banned" }))).toBe("status.banned");
    expect(statusLabelKey(entry({ status: "protected" }))).toBe("status.protected");
    expect(statusLabelKey(entry({ status: "picked" }))).toBe("status.picked");
  });
});

describe("pickBanReserveMap", () => {
  it("is empty for no session, a null snapshot, and an empty snapshot", () => {
    expect(pickBanReserveMap(null).size).toBe(0);
    expect(pickBanReserveMap(session({ slot_reserves: null })).size).toBe(0);
    expect(pickBanReserveMap(session({ slot_reserves: {} })).size).toBe(0);
  });

  it("converts string-keyed positions to a number-keyed Map", () => {
    const map = pickBanReserveMap(session({ slot_reserves: { "1": 41, "3": 43 } }));
    expect(map.get(1)).toBe(41);
    expect(map.get(3)).toBe(43);
    expect(map.get(2)).toBeUndefined();
  });
});
