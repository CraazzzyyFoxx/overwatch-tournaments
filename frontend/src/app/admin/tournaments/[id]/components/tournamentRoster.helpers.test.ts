import { describe, expect, it } from "bun:test";

import {
  buildCaptainOptions,
  buildRosterDraftTree,
  collectRosterDraftSubtreeIds,
  createEmptyRosterDraftPlayer,
  removeRosterDraftPlayer,
  sortRosterDraftPlayers,
  type TeamRosterDraftPlayer,
} from "./tournamentRoster.helpers";

function createDraft(overrides: Partial<TeamRosterDraftPlayer>): TeamRosterDraftPlayer {
  return {
    draft_id: "draft-1",
    player_id: null,
    state: "new",
    name: "Player",
    user_id: 1,
    user_name: "Player One",
    role: "Damage",
    sub_role: "",
    rank: 0,
    is_newcomer: false,
    is_newcomer_role: false,
    is_substitution: false,
    related_player_id: null,
    related_draft_id: null,
    ...overrides,
  };
}

describe("tournamentRoster helpers", () => {
  it("sorts roots by role and nests substitutes directly after their parent chain", () => {
    const players = [
      createDraft({ draft_id: "support", role: "Support", rank: 10 }),
      createDraft({ draft_id: "tank", role: "Tank", rank: 20 }),
      createDraft({
        draft_id: "tank-sub",
        is_substitution: true,
        related_draft_id: "tank",
        rank: 15,
      }),
    ];

    expect(sortRosterDraftPlayers(players).map((player) => player.draft_id)).toEqual([
      "tank",
      "tank-sub",
      "support",
    ]);
  });

  it("builds a tree for base players and substitution chains", () => {
    const players = [
      createDraft({ draft_id: "root" }),
      createDraft({
        draft_id: "sub-1",
        is_substitution: true,
        related_draft_id: "root",
      }),
      createDraft({
        draft_id: "sub-2",
        is_substitution: true,
        related_draft_id: "sub-1",
      }),
    ];

    const tree = buildRosterDraftTree(players);

    expect(tree).toHaveLength(1);
    expect(tree[0]?.player.draft_id).toBe("root");
    expect(tree[0]?.children[0]?.player.draft_id).toBe("sub-1");
    expect(tree[0]?.children[0]?.children[0]?.player.draft_id).toBe("sub-2");
  });

  it("collects the full deletion subtree for a player", () => {
    const players = [
      createDraft({ draft_id: "root" }),
      createDraft({ draft_id: "sub-1", is_substitution: true, related_draft_id: "root" }),
      createDraft({ draft_id: "sub-2", is_substitution: true, related_draft_id: "sub-1" }),
    ];

    expect(collectRosterDraftSubtreeIds(players, "sub-1")).toEqual(["sub-1", "sub-2"]);
  });

  it("removes an existing root and returns only the root id for server-side cascade delete", () => {
    const players = [
      createDraft({ draft_id: "root", player_id: 10, state: "existing" }),
      createDraft({
        draft_id: "sub-1",
        player_id: 11,
        state: "existing",
        is_substitution: true,
        related_draft_id: "root",
      }),
    ];

    const result = removeRosterDraftPlayer(players, "root");

    expect(result.players).toHaveLength(0);
    expect(result.deletedExistingPlayerId).toBe(10);
  });

  it("builds captain options from the active roster and keeps labels unique by user id", () => {
    const players = [
      createDraft({ draft_id: "root", user_id: 1, user_name: "Root Player" }),
      createDraft({
        draft_id: "sub",
        user_id: 2,
        user_name: "Sub Player",
        is_substitution: true,
        related_draft_id: "root",
      }),
      createDraft({
        ...createEmptyRosterDraftPlayer({ draftId: "empty" }),
        user_id: 0,
      }),
    ];

    expect(buildCaptainOptions(players)).toEqual([
      { user_id: 1, label: "Root Player" },
      { user_id: 2, label: "Sub Player" },
    ]);
  });
});
