import { describe, expect, it } from "vitest";

import type { MatchEvent } from "@/types/killfeed.types";
import type { MatchWithStats } from "@/types/encounter.types";
import {
  finalBuild,
  groupKills,
  heldAt,
  laneSnapshot,
  lobbyFirsts,
  readFeed,
  readTeams,
  rivals,
  sampleTimeAt,
  shopPurchases,
  snapshotAt,
  soulsSeries,
  type DlPlayer,
  type DlTeam,
  type Kill
} from "./model";

const player = (memberId: number, side: "home" | "away", stats: Record<string, number> = {}): DlPlayer => ({
  memberId,
  display: { name: `P${memberId}`, tag: null, canonical: null, snapshot: null },
  side,
  hero: null,
  stats
});
const TEAMS: [DlTeam, DlTeam] = [
  { id: 10, name: "Home", side: "home", gameSide: "hidden_king", players: [player(1, "home"), player(2, "home")] },
  { id: 20, name: "Away", side: "away", gameSide: "archmother", players: [player(3, "away")] }
];

let nextId = 0;
const event = (type: string, overrides: Partial<MatchEvent>): MatchEvent => ({
  id: ++nextId,
  segment: 0,
  t: 0,
  type,
  actor_member_id: null,
  actor_team_id: null,
  target_member_id: null,
  target_team_id: null,
  entity_id: null,
  related_entity_id: null,
  data: null,
  ...overrides
});

describe("readFeed", () => {
  it("reads every event kind into its own list and skips malformed data", () => {
    const feed = readFeed(
      [
        event("kill", { t: 5, actor_member_id: 3, actor_team_id: 20, target_member_id: 1 }),
        event("objective", { t: 443, actor_team_id: 10, target_team_id: 20, data: { objective: 3 } }),
        event("mid_boss", { t: 900, actor_team_id: 10, target_team_id: 20 }),
        event("purchase", { t: 12, actor_member_id: 1, data: { item_id: 10 } }),
        event("purchase", { t: 40, actor_member_id: 1, data: { item_id: 11, sold_t: 90, imbued_ability_id: 7 } }),
        event("purchase", { t: 41, actor_member_id: 1, data: { item_id: "12" } }),
        event("snapshot", { t: 360, actor_member_id: 1, data: { net_worth: 900 } }),
        event("snapshot", { t: 180, actor_member_id: 1, data: { net_worth: 400, label: "x" } }),
        event("lane", { actor_member_id: 1, data: { lane: 4 } }),
        event("damage", { actor_member_id: 1, target_member_id: 3, data: { amount: 500 } }),
        event("damage_source", { actor_member_id: 1, data: { source: "upgrade_capacitor", amount: 200 } })
      ],
      TEAMS
    );

    expect(feed.kills).toEqual([{ t: 5, killer: 3, victim: 1, side: "away" }]);
    expect(feed.objectives).toEqual([{ t: 443, objective: 3, owner: "away" }]);
    expect(feed.midBoss).toEqual([{ t: 900, killer: "home", claimer: "away" }]);
    expect(feed.snapshots.get(1)).toEqual([
      { t: 180, values: { net_worth: 400 } },
      { t: 360, values: { net_worth: 900 } }
    ]);
    expect(feed.lanes.get(1)).toBe(4);
    expect(feed.damageTo.get(1)).toEqual([{ target: 3, amount: 500 }]);
    expect(feed.damageBySource.get(1)).toEqual([{ source: "upgrade_capacitor", amount: 200 }]);

    const shop = shopPurchases(feed, 1, (id) => id === 10 || id === 11);
    expect(shop).toEqual([
      { itemId: 10, t: 12, soldT: null, imbuedAbilityId: null },
      { itemId: 11, t: 40, soldT: 90, imbuedAbilityId: 7 }
    ]);
    expect(finalBuild(shop).map((purchase) => purchase.itemId)).toEqual([10]);
    expect(laneSnapshot(feed, 1)?.t).toBe(360);
  });
});

describe("groupKills", () => {
  const kill = (t: number, side: "home" | "away"): Kill => ({ t, killer: null, victim: null, side });

  it("chains kills up to 15 s apart, numbers chains of three or more, and merges neighbouring picks", () => {
    const groups = groupKills([
      kill(10, "home"),
      kill(100, "away"),
      kill(200, "home"),
      kill(210, "away"),
      kill(225, "home"), // 15 s after the last: same fight
      kill(400, "away")
    ]);

    expect(groups.map(({ no, from, to, home, away, winner }) => ({ no, from, to, home, away, winner }))).toEqual([
      { no: null, from: 10, to: 100, home: 1, away: 1, winner: null },
      { no: 1, from: 200, to: 225, home: 2, away: 1, winner: "home" },
      { no: null, from: 400, to: 400, home: 0, away: 1, winner: "away" }
    ]);
  });
});

describe("soulsSeries", () => {
  it("sums each side per sample time, a missing sample holding the player's last value", () => {
    const feed = readFeed(
      [
        event("snapshot", { t: 180, actor_member_id: 1, data: { net_worth: 100 } }),
        event("snapshot", { t: 360, actor_member_id: 1, data: { net_worth: 300 } }),
        event("snapshot", { t: 180, actor_member_id: 2, data: { net_worth: 50 } }),
        event("snapshot", { t: 360, actor_member_id: 3, data: { net_worth: 200 } })
      ],
      TEAMS
    );

    expect(soulsSeries(TEAMS[0].players, TEAMS[1].players, feed)).toEqual([
      { t: 0, home: 0, away: 0 },
      { t: 180, home: 150, away: 0 },
      { t: 360, home: 350, away: 200 }
    ]);
  });
});

describe("rivals and lobby firsts", () => {
  it("names the most frequent killer and victim, and counts ties as firsts for each", () => {
    const feed = readFeed(
      [
        event("kill", { actor_member_id: 3, target_member_id: 1 }),
        event("kill", { actor_member_id: 3, target_member_id: 1 }),
        event("kill", { actor_member_id: 1, target_member_id: 3 })
      ],
      TEAMS
    );
    expect(rivals(feed, 1)).toEqual({ nemesis: { memberId: 3, count: 2 }, victim: { memberId: 3, count: 1 } });

    const a = player(1, "home", { kills: 5, deaths: 2, denies: 0 });
    const b = player(3, "away", { kills: 5, deaths: 4, denies: 0 });
    expect(lobbyFirsts(a, [a, b])).toEqual(["kills", "deaths"]);
    expect(lobbyFirsts(b, [a, b])).toEqual(["kills"]);
  });
});

describe("the match at one moment", () => {
  it("reads the last sample by then, keeps what was held, and drops an item the moment it is sold", () => {
    const feed = readFeed(
      [
        event("snapshot", { t: 180, actor_member_id: 1, data: { net_worth: 100 } }),
        event("snapshot", { t: 360, actor_member_id: 1, data: { net_worth: 300 } }),
        event("snapshot", { t: 540, actor_member_id: 3, data: { net_worth: 500 } })
      ],
      TEAMS
    );
    expect(snapshotAt(feed, 1, 100)).toBeNull();
    expect(snapshotAt(feed, 1, 359)?.values.net_worth).toBe(100);
    expect(snapshotAt(feed, 1, 360)?.values.net_worth).toBe(300);
    expect(sampleTimeAt(feed, 500)).toBe(360);

    const bought = { itemId: 1, t: 100, soldT: 400, imbuedAbilityId: null };
    const kept = { itemId: 2, t: 300, soldT: null, imbuedAbilityId: null };
    expect(heldAt([bought, kept], 99)).toEqual([]);
    expect(heldAt([bought, kept], 399)).toEqual([bought, kept]);
    expect(heldAt([bought, kept], 400)).toEqual([kept]);
  });

  it("names the side each participation played from its source order, never from its seat", () => {
    const participant = (id: number, source_position: number) => ({ encounter_team_id: id, name: `T${id}`, source_position });
    const match = {
      participants: [participant(10, 2), participant(20, 1)],
      statistics: { members: [], facts: [], entities: [], segments: [] }
    } as unknown as MatchWithStats;
    expect(readTeams(match)?.map((team) => [team.side, team.gameSide])).toEqual([
      ["home", "archmother"],
      ["away", "hidden_king"]
    ]);
  });
});
