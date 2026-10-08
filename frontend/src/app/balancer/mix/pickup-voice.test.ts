import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/error";
import type {
  CustomGame,
  CustomGameLobby,
  MixVoiceOptions,
} from "@/services/custom-game.service";

import { busyVoices, voiceBlocker, voicePatch, voiceRefusal } from "./pickup-voice";

function lobby(overrides: Partial<CustomGameLobby> = {}): CustomGameLobby {
  return {
    lobby_index: 0,
    selected_variant_index: 0,
    next_map_id: null,
    balanced_at: null,
    team1_voice_channel_id: null,
    team2_voice_channel_id: null,
    ...overrides,
  };
}

function game(overrides: Partial<CustomGame> = {}): CustomGame {
  return {
    id: 1,
    workspace_id: 7,
    host_user_id: 9,
    co_hosts: [],
    host_display_name: null,
    name: "Thursday",
    status: "draft",
    settings: { points_per_win: 0, team_names: {}, workspace_discord_channel_id: null },
    created_at: null,
    lobby_count: 1,
    lobbies: [lobby()],
    roster_shape: null,
    matches_count: 0,
    last_match_at: null,
    self_signup: "closed",
    self_role_edit: false,
    general_voice_channel_id: null,
    ...overrides,
  };
}

function options(overrides: Partial<MixVoiceOptions> = {}): MixVoiceOptions {
  return {
    category_id: "100",
    category_missing_permissions: null,
    general: [{ id: "1", name: "Lobby", missing_permissions: null }],
    team: [
      { id: "2", name: "Team 1", missing_permissions: null },
      { id: "3", name: "Team 2", missing_permissions: ["move_members"] },
    ],
    error: null,
    ...overrides,
  };
}

describe("busyVoices", () => {
  it("maps every team voice of the workspace's other open mixes to the mix that took it", () => {
    const busy = busyVoices(
      [
        game({ id: 1, lobbies: [lobby({ team1_voice_channel_id: "2", team2_voice_channel_id: "3" })] }),
        game({
          id: 2,
          name: "Friday",
          status: "balanced",
          lobby_count: 2,
          lobbies: [lobby(), lobby({ lobby_index: 1, team1_voice_channel_id: "4" })],
        }),
      ],
      1,
    );

    // The current mix's own picks are not "busy" -- it is the one editing them.
    expect(busy.get("2")).toBeUndefined();
    expect(busy.get("3")).toBeUndefined();
    expect(busy.get("4")).toEqual({ gameName: "Friday", lobbyIndex: 1 });
  });

  it("ignores finished mixes: their voices are free again", () => {
    for (const status of ["completed", "cancelled"] as const) {
      const busy = busyVoices(
        [game({ id: 2, status, lobbies: [lobby({ team1_voice_channel_id: "4" })] })],
        1,
      );
      expect(busy.size).toBe(0);
    }
  });
});

describe("voiceBlocker", () => {
  it("unions the category's gaps with the gaps of the voices actually picked", () => {
    const blocked = voiceBlocker(
      options({
        category_missing_permissions: ["view_channel"],
        team: [
          { id: "2", name: "Team 1", missing_permissions: ["connect"] },
          { id: "3", name: "Team 2", missing_permissions: ["connect", "move_members"] },
        ],
      }),
      ["1", "2", "3"],
    );

    expect(blocked.toSorted()).toEqual(["connect", "move_members", "view_channel"]);
  });

  it("stays empty while nothing is missing and while the options are still loading", () => {
    expect(voiceBlocker(options(), ["1", "2", null])).toEqual([]);
    expect(voiceBlocker(undefined, ["1"])).toEqual([]);
  });
});

describe("voicePatch", () => {
  const current = game({
    general_voice_channel_id: "1",
    lobby_count: 2,
    lobbies: [
      lobby({ team1_voice_channel_id: "2", team2_voice_channel_id: "3" }),
      lobby({ lobby_index: 1, team1_voice_channel_id: "4", team2_voice_channel_id: "5" }),
    ],
  });

  it("changes one lobby's one team and leaves every other pick exactly where it was", () => {
    expect(voicePatch(current, { lobbyIndex: 1, team: 1, channelId: "9" })).toEqual({
      general_voice_channel_id: "1",
      lobbies: [
        { lobby_index: 0, team1_voice_channel_id: "2", team2_voice_channel_id: "3" },
        { lobby_index: 1, team1_voice_channel_id: "9", team2_voice_channel_id: "5" },
      ],
    });
  });

  it("clears a pick when the change carries no channel", () => {
    expect(voicePatch(current, { lobbyIndex: 0, team: 2, channelId: null }).lobbies[0]).toEqual({
      lobby_index: 0,
      team1_voice_channel_id: "2",
      team2_voice_channel_id: null,
    });
  });

  it("changes the general voice without touching a lobby", () => {
    const patch = voicePatch(current, { general: null });

    expect(patch.general_voice_channel_id).toBeNull();
    expect(patch.lobbies).toEqual([
      { lobby_index: 0, team1_voice_channel_id: "2", team2_voice_channel_id: "3" },
      { lobby_index: 1, team1_voice_channel_id: "4", team2_voice_channel_id: "5" },
    ]);
  });
});

describe("voiceRefusal", () => {
  it("names the refusal the server slug stands for, so the page can say it in the reader's language", () => {
    const error = new ApiError(409, [{ msg: "general_voice_outside_category", code: "conflict" }]);

    expect(voiceRefusal(error)).toBe("general_voice_outside_category");
    expect(voiceRefusal(new ApiError(503, [{ msg: "discord_unavailable", code: "unavailable" }]))).toBe(
      "discord_unavailable",
    );
  });

  it("leaves anything else to the generic error toast", () => {
    expect(voiceRefusal(new ApiError(403, [{ msg: "forbidden", code: "forbidden" }]))).toBeNull();
    expect(voiceRefusal(new Error("offline"))).toBeNull();
  });
});
