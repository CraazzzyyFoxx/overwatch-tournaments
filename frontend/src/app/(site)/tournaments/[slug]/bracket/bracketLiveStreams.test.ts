import { describe, expect, it } from "vitest";

import type { StreamEntry, TournamentStreams } from "@/types/stream.types";

import { buildLiveTeamStreams, liveStreamForPlayers } from "./bracketLiveStreams";

function entry(overrides: Partial<StreamEntry> & { channel: string }): StreamEntry {
  return {
    platform: "twitch",
    url: `https://twitch.tv/${overrides.channel}`,
    live: true,
    title: null,
    game_name: null,
    viewer_count: null,
    thumbnail_url: null,
    started_at: null,
    player: null,
    ...overrides
  };
}

function participant(
  channel: string,
  player: string,
  team: { id: number; name: string } | null,
  viewerCount: number | null
): StreamEntry {
  return entry({
    channel,
    viewer_count: viewerCount,
    player: { id: 1, name: player, avatar_url: null, team }
  });
}

function streams(overrides: Partial<TournamentStreams> = {}): TournamentStreams {
  return { official: [], participants: [], ...overrides };
}

describe("buildLiveTeamStreams", () => {
  it("is empty while the stream query has not resolved", () => {
    expect(buildLiveTeamStreams(undefined).size).toBe(0);
  });

  // A player streaming during check-in has no roster yet. That is an ordinary
  // state, and there is no bracket slot to attach the stream to.
  it("skips a participant with no team in this tournament", () => {
    const map = buildLiveTeamStreams(
      streams({ participants: [participant("solo", "Solo", null, 120)] })
    );

    expect(map.size).toBe(0);
  });

  // The caster belongs to the broadcast, not to a side of the match. Attributing
  // it to a team would light up slots while nobody on them is streaming.
  it("ignores official broadcasts entirely", () => {
    const map = buildLiveTeamStreams(
      streams({
        official: [
          entry({
            channel: "owt_main",
            viewer_count: 5_000,
            player: { id: 9, name: "Caster", avatar_url: null, team: { id: 7, name: "Nova" } }
          })
        ]
      })
    );

    expect(map.size).toBe(0);
  });

  it("keys the winning stream by the tournament team id", () => {
    const map = buildLiveTeamStreams(
      streams({
        participants: [participant("aria", "Aria", { id: 7, name: "Nova" }, 40)]
      })
    );

    expect(map.get(7)?.channel).toBe("aria");
    expect(map.get(7)?.player?.team?.name).toBe("Nova");
  });

  it("names the biggest audience when a team has two players on air", () => {
    const map = buildLiveTeamStreams(
      streams({
        participants: [
          participant("small", "Small", { id: 7, name: "Nova" }, 12),
          participant("big", "Big", { id: 7, name: "Nova" }, 900)
        ]
      })
    );

    expect(map.size).toBe(1);
    expect(map.get(7)?.channel).toBe("big");
  });

  // `null` is "the platform reports no count", not "zero viewers", so it must
  // never displace a channel with a real number — in either arrival order.
  it("never lets an unmeasured channel outrank a counted one", () => {
    const counted = participant("counted", "Counted", { id: 7, name: "Nova" }, 3);
    const unmeasured = participant("unmeasured", "Unmeasured", { id: 7, name: "Nova" }, null);

    expect(buildLiveTeamStreams(streams({ participants: [counted, unmeasured] })).get(7)?.channel).toBe(
      "counted"
    );
    expect(buildLiveTeamStreams(streams({ participants: [unmeasured, counted] })).get(7)?.channel).toBe(
      "counted"
    );
  });

  // The bracket refetches every 15s while a tournament is live. Without a total
  // order, two equally-watched streams would swap the named player on each poll.
  it("resolves a tie the same way regardless of arrival order", () => {
    const alpha = participant("alpha", "Alpha", { id: 7, name: "Nova" }, 50);
    const beta = participant("beta", "Beta", { id: 7, name: "Nova" }, 50);

    expect(buildLiveTeamStreams(streams({ participants: [alpha, beta] })).get(7)?.channel).toBe(
      "alpha"
    );
    expect(buildLiveTeamStreams(streams({ participants: [beta, alpha] })).get(7)?.channel).toBe(
      "alpha"
    );
  });

  it("resolves a tie of two unmeasured channels stably too", () => {
    const alpha = participant("alpha", "Alpha", { id: 7, name: "Nova" }, null);
    const beta = participant("beta", "Beta", { id: 7, name: "Nova" }, null);

    expect(buildLiveTeamStreams(streams({ participants: [alpha, beta] })).get(7)?.channel).toBe(
      "alpha"
    );
    expect(buildLiveTeamStreams(streams({ participants: [beta, alpha] })).get(7)?.channel).toBe(
      "alpha"
    );
  });

  it("keeps one winner per team", () => {
    const map = buildLiveTeamStreams(
      streams({
        participants: [
          participant("nova-a", "A", { id: 7, name: "Nova" }, 10),
          participant("void-a", "B", { id: 8, name: "Void" }, 4),
          participant("nova-b", "C", { id: 7, name: "Nova" }, 99)
        ]
      })
    );

    expect(map.size).toBe(2);
    expect(map.get(7)?.channel).toBe("nova-b");
    expect(map.get(8)?.channel).toBe("void-a");
  });
});

describe("liveStreamForPlayers", () => {
  const onAir = (channel: string, playerId: number, viewerCount: number | null) =>
    entry({
      channel,
      viewer_count: viewerCount,
      player: { id: playerId, name: channel, avatar_url: null, team: null }
    });

  it("names the most-watched stream among the seat's players, ignoring everyone else", () => {
    const result = liveStreamForPlayers(
      streams({ participants: [onAir("a", 1, 5), onAir("b", 2, 50), onAir("c", 3, 500)] }),
      new Set([1, 2])
    );
    expect(result?.channel).toBe("b");
  });

  it("is undefined while the query has not resolved or nobody in the seat is on air", () => {
    expect(liveStreamForPlayers(undefined, new Set([1]))).toBeUndefined();
    expect(liveStreamForPlayers(streams({ participants: [onAir("a", 9, 1)] }), new Set([1]))).toBeUndefined();
  });
});
