import { describe, expect, it } from "vitest";

import type { CatalogEntityRead } from "@/types/catalog.types";
import { LogStatsName } from "../stat-names";

import { bestRuns, readFlow, roleDuels } from "./breakdown.model";
import type { TimelineKill } from "./timeline";
import type { OwPlayer } from "./view";

const HOME = 1;
const AWAY = 2;

const hero = (id: number, cls: string) => ({ id, name: `Hero ${id}`, attrs: { class: cls } }) as unknown as CatalogEntityRead;

const player = (id: number, cls: string, stats: Partial<Record<LogStatsName, number>>): OwPlayer => ({
  workspace_member_id: id,
  user_id: id,
  display: { name: `P${id}`, tag: "#1", canonical: null, snapshot: null },
  stats: { 0: stats as Record<string, number> },
  heroes: {},
  heroTimes: { 0: [{ entity: hero(id, cls), seconds: 300 }] }
});

const kill = (time: number, killerTeam: number | null): TimelineKill => ({
  time,
  round: 1,
  fight: 1,
  ability: null,
  damage: null,
  is_critical_hit: null,
  is_environmental: null,
  killer_member_id: null,
  killer_team_id: killerTeam,
  killer_entity: null,
  victim_member_id: null,
  victim_team_id: null,
  victim_entity: null
});

describe("roleDuels", () => {
  it("gives the win on a reverted stat to the side with fewer deaths", () => {
    const home = { players: [player(1, "tank", { [LogStatsName.Deaths]: 2 })] };
    const away = { players: [player(2, "tank", { [LogStatsName.Deaths]: 5 })] };
    const [tank] = roleDuels(home, away, 0);
    const deaths = tank.duels[0].stats.find((stat) => stat.name === LogStatsName.Deaths);
    expect(deaths?.winner).toBe("home");
  });

  it("pairs best against best and leaves the surplus player an empty side", () => {
    const dmg = (value: number) => ({ [LogStatsName.HeroDamageDealt]: value });
    const home = { players: [player(1, "damage", dmg(1000)), player(2, "damage", dmg(5000))] };
    const away = { players: [player(3, "damage", dmg(3000))] };
    const [damage] = roleDuels(home, away, 0);
    expect(damage.duels).toHaveLength(2);
    expect(damage.duels[0].home?.workspace_member_id).toBe(2);
    expect(damage.duels[0].away?.workspace_member_id).toBe(3);
    expect(damage.duels[1].home?.workspace_member_id).toBe(1);
    expect(damage.duels[1].away).toBeNull();
    // Nothing to win against an empty side.
    expect(damage.duels[1].wins).toEqual({ home: 0, away: 0 });
  });
});

describe("bestRuns", () => {
  it("finds each side's longest unanswered run across alternating kills", () => {
    const kills = [
      kill(10, HOME),
      kill(20, AWAY),
      kill(30, AWAY),
      kill(40, AWAY),
      kill(50, HOME),
      kill(60, HOME)
    ];
    expect(bestRuns(kills, HOME, AWAY)).toEqual({
      home: { n: 2, from: 50, to: 60 },
      away: { n: 3, from: 20, to: 40 }
    });
  });

  it("neither counts an unknown-side kill nor lets a run span it", () => {
    const kills = [kill(10, HOME), kill(20, null), kill(30, HOME)];
    expect(bestRuns(kills, HOME, AWAY).home?.n).toBe(1);
  });
});

describe("readFlow", () => {
  it("moves the difference only for kills with a known side", () => {
    const flow = readFlow([kill(10, HOME), kill(20, null), kill(30, AWAY), kill(40, AWAY)], [], HOME, AWAY);
    expect(flow?.points.map((point) => point.diff)).toEqual([1, 0, -1]);
    expect(flow?.top).toBe(2);
    expect(flow?.bottom).toBe(2);
  });
});
