import { tierAt } from "@/components/rank/rank-history-model";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { NativeTier } from "@/types/discipline.types";
import type { MatchWithStats } from "@/types/encounter.types";
import type { PersonDisplay } from "@/types/user.types";
import type { MatchEvent } from "@/types/killfeed.types";
import { objectiveOf } from "./objectives";

/**
 * The Deadlock match as its view reads it: two sides (the first participation is home), their players with their
 * whole-match facts, and the decoder's events (`shared/disciplines/deadlock/ingest.py` documents each `data`).
 */

export type Side = "home" | "away";
/** The in-game side a participation played: the decoder's `team0` and `team1`, in that order. */
export type GameSide = "hidden_king" | "archmother";

export interface DlPlayer {
  memberId: number;
  /** How the match names the player (the Steam persona); `display.canonical` builds the profile link. */
  display: PersonDisplay;
  side: Side;
  hero: CatalogEntityRead | null;
  /** The rank the player held on the match date, a step of the game's ladder; `null` when none was known. */
  rank: NativeTier | null;
  /** Whole-match facts by stat code. */
  stats: Record<string, number>;
}

export interface DlTeam {
  id: number;
  name: string;
  side: Side;
  /** `null` when the observation carries no source order (it always does for a decoded match). */
  gameSide: GameSide | null;
  /** Most souls first: the order the game's own scoreboard uses. */
  players: DlPlayer[];
}

export interface Kill {
  t: number;
  killer: number | null;
  victim: number | null;
  side: Side | null;
}

export interface Objective {
  t: number;
  /** `ECitadelTeamObjective`. */
  objective: number;
  /** The side that lost it; the other side destroyed it. */
  owner: Side | null;
}

export interface MidBoss {
  t: number;
  killer: Side | null;
  claimer: Side | null;
}

export interface Purchase {
  itemId: number;
  t: number;
  /** When it left the inventory (sold, or consumed by an upgrade); `null` while held to the end. */
  soldT: number | null;
  imbuedAbilityId: number | null;
}

export interface Snapshot {
  t: number;
  values: Record<string, number>;
}

export interface MatchFeed {
  kills: Kill[];
  objectives: Objective[];
  midBoss: MidBoss[];
  /** Every `purchase` per member, abilities included: `shopPurchases` keeps the shop ones. */
  purchases: Map<number, Purchase[]>;
  snapshots: Map<number, Snapshot[]>;
  /** `CMsgLaneColor` per member. */
  lanes: Map<number, number>;
  damageTo: Map<number, { target: number; amount: number }[]>;
  damageBySource: Map<number, { source: string; amount: number }[]>;
}

const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);

const push = <K, V>(map: Map<K, V[]>, key: K, value: V) => {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
};

/** The two sides of a Deadlock match, or `null` when it is not a duel of two participations; ranks read on `ladder`. */
export function readTeams(
  match: Pick<MatchWithStats, "participants" | "statistics">,
  ladder: readonly NativeTier[] = []
): [DlTeam, DlTeam] | null {
  if (match.participants.length !== 2) return null;
  const entities = new Map(match.statistics.entities.map((entity) => [entity.id, entity]));
  const [home, away] = match.participants.map((participant, index): DlTeam => {
    const side: Side = index === 0 ? "home" : "away";
    const players = match.statistics.members
      .filter((member) => member.encounter_team_id === participant.encounter_team_id)
      .map((member): DlPlayer => {
        const facts = match.statistics.facts.filter(
          (fact) =>
            fact.segment === 0 &&
            fact.workspace_member_id === member.workspace_member_id &&
            fact.encounter_team_id === member.encounter_team_id
        );
        const heroId = facts.find((fact) => fact.entity_id != null)?.entity_id;
        return {
          memberId: member.workspace_member_id,
          display: member.display,
          side,
          hero: heroId == null ? null : (entities.get(heroId) ?? null),
          rank: tierAt(ladder, member.rank_value) ?? null,
          stats: Object.fromEntries(facts.map((fact) => [fact.stat_code, fact.value]))
        };
      })
      .sort((a, b) => (b.stats.net_worth ?? 0) - (a.stats.net_worth ?? 0));
    // `stats.match_team.source_position` counts from 1 in the decoder's team order: 1 is `team0`, 2 is `team1`.
    const position = participant.source_position;
    const gameSide: GameSide | null = position === 1 ? "hidden_king" : position === 2 ? "archmother" : null;
    return { id: participant.encounter_team_id, name: participant.name, side, gameSide, players };
  });
  return [home, away];
}

/** The decoder's events, read once into what each tab draws. */
export function readFeed(events: readonly MatchEvent[], teams: readonly [DlTeam, DlTeam]): MatchFeed {
  const sideOf = (teamId: number | null): Side | null =>
    teamId === teams[0].id ? "home" : teamId === teams[1].id ? "away" : null;
  const feed: MatchFeed = {
    kills: [],
    objectives: [],
    midBoss: [],
    purchases: new Map(),
    snapshots: new Map(),
    lanes: new Map(),
    damageTo: new Map(),
    damageBySource: new Map()
  };
  for (const event of events) {
    const data = event.data ?? {};
    const actor = event.actor_member_id;
    switch (event.type) {
      case "kill":
        feed.kills.push({ t: event.t, killer: actor, victim: event.target_member_id, side: sideOf(event.actor_team_id) });
        break;
      case "objective": {
        const objective = num(data.objective);
        if (objective !== null) feed.objectives.push({ t: event.t, objective, owner: sideOf(event.target_team_id) });
        break;
      }
      case "mid_boss":
        feed.midBoss.push({ t: event.t, killer: sideOf(event.actor_team_id), claimer: sideOf(event.target_team_id) });
        break;
      case "purchase": {
        const itemId = num(data.item_id);
        if (actor != null && itemId !== null) {
          push(feed.purchases, actor, {
            itemId,
            t: event.t,
            soldT: num(data.sold_t),
            imbuedAbilityId: num(data.imbued_ability_id)
          });
        }
        break;
      }
      case "snapshot":
        if (actor != null) {
          const values: Record<string, number> = {};
          for (const [code, value] of Object.entries(data)) {
            const n = num(value);
            if (n !== null) values[code] = n;
          }
          push(feed.snapshots, actor, { t: event.t, values });
        }
        break;
      case "lane": {
        const lane = num(data.lane);
        if (actor != null && lane !== null) feed.lanes.set(actor, lane);
        break;
      }
      case "damage": {
        const amount = num(data.amount);
        if (actor != null && event.target_member_id != null && amount !== null) {
          push(feed.damageTo, actor, { target: event.target_member_id, amount });
        }
        break;
      }
      case "damage_source": {
        const amount = num(data.amount);
        if (actor != null && typeof data.source === "string" && amount !== null) {
          push(feed.damageBySource, actor, { source: data.source, amount });
        }
        break;
      }
    }
  }
  for (const list of feed.snapshots.values()) list.sort((a, b) => a.t - b.t);
  return feed;
}

/** A member's shop purchases in time order; `isShopItem` (the asset's `type`) drops the ability points. */
export const shopPurchases = (feed: MatchFeed, memberId: number, isShopItem: (itemId: number) => boolean) =>
  (feed.purchases.get(memberId) ?? []).filter((purchase) => isShopItem(purchase.itemId));

/** What the player ended the match holding, in purchase order. */
export const finalBuild = (purchases: readonly Purchase[]): Purchase[] =>
  purchases.filter((purchase) => purchase.soldT === null);

// ── The match at one moment ──────────────────────────────────────────────────

/** The `snapshot` counters, i.e. what the view can show at any moment of the match. */
export const TIMED_STATS: Record<string, true> = {
  net_worth: true,
  kills: true,
  deaths: true,
  assists: true,
  creep_kills: true,
  neutral_kills: true,
  denies: true,
  player_damage: true,
  player_damage_taken: true,
  player_healing: true,
  boss_damage: true,
  level: true
};

/** The player's last sample taken by `t`; `null` before the first one. */
export const snapshotAt = (feed: MatchFeed, memberId: number, t: number): Snapshot | null => {
  let found: Snapshot | null = null;
  for (const snap of feed.snapshots.get(memberId) ?? []) {
    if (snap.t > t) break;
    found = snap;
  }
  return found;
};

/** The latest sample time any player has by `t` (the samples are shared), `0` before the first. */
export const sampleTimeAt = (feed: MatchFeed, t: number): number => {
  let latest = 0;
  for (const list of feed.snapshots.values()) {
    for (const snap of list) {
      if (snap.t > t) break;
      if (snap.t > latest) latest = snap.t;
    }
  }
  return latest;
};

/** What the player held at `t`: bought by then and not yet sold (or consumed by an upgrade). */
export const heldAt = (purchases: readonly Purchase[], t: number): Purchase[] =>
  purchases.filter((purchase) => purchase.t <= t && (purchase.soldT === null || purchase.soldT > t));

/**
 * A player's figures at `t`: the end facts at the end, else his last sample by then with kills and deaths counted
 * from the kill events (exact to the second).
 */
export function statsAt(player: DlPlayer, feed: MatchFeed | null, t: number, atEnd: boolean): Record<string, number> {
  if (atEnd || !feed) return player.stats;
  const kills = feed.kills.filter((kill) => kill.t <= t && kill.killer === player.memberId).length;
  const deaths = feed.kills.filter((kill) => kill.t <= t && kill.victim === player.memberId).length;
  return { ...(snapshotAt(feed, player.memberId, t)?.values ?? {}), kills, deaths };
}

/** A team's headline at `t`: kills, souls and the enemy structures it had destroyed. */
export function teamAt(team: DlTeam, feed: MatchFeed, t: number, atEnd: boolean) {
  const stats = team.players.map((player) => statsAt(player, feed, t, atEnd));
  return {
    kills: stats.reduce((total, s) => total + (s.kills ?? 0), 0),
    souls: stats.reduce((total, s) => total + (s.net_worth ?? 0), 0),
    objectives: feed.objectives.filter((objective) => objective.owner !== null && objective.owner !== team.side && objective.t <= t).length
  };
}

// ── Metrics ──────────────────────────────────────────────────────────────────

export interface MetricContext {
  /** Match length in minutes; `null` when the match recorded none. */
  minutes: number | null;
  /** Kills of the player's team, for kill participation. */
  teamKills: number;
}

const ratio = (part: number | undefined, whole: number | undefined) =>
  part == null || whole == null || whole <= 0 ? null : part / whole;

/** A derived figure of one player, `null` when the facts it needs are missing. Formulas are the standard ones. */
export const METRICS: Record<string, (stats: Record<string, number>, ctx: MetricContext) => number | null> = {
  souls_per_min: (s, ctx) => (ctx.minutes ? ratio(s.net_worth, ctx.minutes) : null),
  damage_per_min: (s, ctx) => (ctx.minutes ? ratio(s.player_damage, ctx.minutes) : null),
  /** Lives are deaths + 1. */
  damage_per_life: (s) => (s.player_damage == null || s.deaths == null ? null : s.player_damage / (s.deaths + 1)),
  taken_per_life: (s) => (s.player_damage_taken == null || s.deaths == null ? null : s.player_damage_taken / (s.deaths + 1)),
  accuracy: (s) => ratio(s.shots_hit, (s.shots_hit ?? 0) + (s.shots_missed ?? 0)),
  headshot_rate: (s) => ratio(s.hero_bullets_hit_crit, s.hero_bullets_hit),
  kill_participation: (s, ctx) => ratio((s.kills ?? 0) + (s.assists ?? 0), ctx.teamKills)
};

export const teamSum = (team: DlTeam, code: string): number | null => {
  const values = team.players.map((player) => player.stats[code]).filter((value) => value != null);
  return values.length ? values.reduce((a, b) => a + b, 0) : null;
};

export const minutesOf = (durationS: number | null | undefined) => (durationS ? durationS / 60 : null);

// ── Fights ───────────────────────────────────────────────────────────────────

/** Kills further apart than this are separate engagements (on real matches a wider gap chains the lanes together). */
export const FIGHT_GAP_S = 15;
/** An engagement with fewer kills is a pick, not a fight. */
export const FIGHT_MIN_KILLS = 3;

export interface KillGroup {
  /** 1-based number among the fights; `null` for a run of picks. */
  no: number | null;
  kills: Kill[];
  from: number;
  to: number;
  home: number;
  away: number;
  winner: Side | null;
}

/**
 * The kills as engagements: kills no more than `FIGHT_GAP_S` apart chain into one, an engagement of at least
 * `FIGHT_MIN_KILLS` is a numbered fight, and neighbouring smaller ones merge into one run of picks.
 */
export function groupKills(kills: readonly Kill[]): KillGroup[] {
  const sorted = [...kills].sort((a, b) => a.t - b.t);
  const chains: Kill[][] = [];
  for (const kill of sorted) {
    const last = chains.at(-1);
    if (last && kill.t - last[last.length - 1].t <= FIGHT_GAP_S) last.push(kill);
    else chains.push([kill]);
  }
  const groups: KillGroup[] = [];
  let fights = 0;
  for (const chain of chains) {
    const fight = chain.length >= FIGHT_MIN_KILLS;
    const previous = groups.at(-1);
    if (!fight && previous && previous.no === null) {
      previous.kills.push(...chain);
    } else {
      groups.push({ no: fight ? ++fights : null, kills: [...chain], from: 0, to: 0, home: 0, away: 0, winner: null });
    }
  }
  for (const group of groups) {
    group.from = group.kills[0].t;
    group.to = group.kills[group.kills.length - 1].t;
    group.home = group.kills.filter((kill) => kill.side === "home").length;
    group.away = group.kills.filter((kill) => kill.side === "away").length;
    group.winner = group.home === group.away ? null : group.home > group.away ? "home" : "away";
  }
  return groups;
}

// ── Souls over time ──────────────────────────────────────────────────────────

export interface SoulsPoint {
  t: number;
  home: number;
  away: number;
}

/** Two groups' souls at every sample time (whole teams, or a lane's players); a missing sample keeps the last one. */
export function soulsSeries(home: readonly DlPlayer[], away: readonly DlPlayer[], feed: MatchFeed): SoulsPoint[] {
  const times = [...new Set([...feed.snapshots.values()].flatMap((list) => list.map((snap) => snap.t)))].sort(
    (a, b) => a - b
  );
  const at = (memberId: number, t: number) => {
    let value = 0;
    for (const snap of feed.snapshots.get(memberId) ?? []) {
      if (snap.t > t) break;
      value = snap.values.net_worth ?? value;
    }
    return value;
  };
  const sum = (players: readonly DlPlayer[], t: number) => players.reduce((total, player) => total + at(player.memberId, t), 0);
  return [{ t: 0, home: 0, away: 0 }, ...times.map((t) => ({ t, home: sum(home, t), away: sum(away, t) }))];
}

// ── Lanes ────────────────────────────────────────────────────────────────────

/** Laning is read from the sample taken at this time (the game samples every three minutes early on). */
export const LANE_CUTOFF_S = 540;

/** `CMsgLaneColor`, in map order. */
export const LANE_ORDER = [1, 3, 4, 6] as const;

/** The player's sample at the laning cutoff: the last one taken by then. */
export const laneSnapshot = (feed: MatchFeed, memberId: number): Snapshot | null =>
  (feed.snapshots.get(memberId) ?? []).filter((snap) => snap.t <= LANE_CUTOFF_S).at(-1) ?? null;

export interface Lane {
  lane: number;
  home: DlPlayer[];
  away: DlPlayer[];
}

export function readLanes(teams: readonly [DlTeam, DlTeam], feed: MatchFeed): Lane[] {
  const of = (team: DlTeam, lane: number) => team.players.filter((player) => feed.lanes.get(player.memberId) === lane);
  return LANE_ORDER.map((lane) => ({ lane, home: of(teams[0], lane), away: of(teams[1], lane) })).filter(
    (lane) => lane.home.length + lane.away.length > 0
  );
}

/** A lane's three structures, from the lane out to the base. */
export const LANE_STRUCTURES = ["guardian", "walker", "baseGuardian"] as const;
export type LaneStructure = (typeof LANE_STRUCTURES)[number];

/** When each side's structures in `lane` fell (`null`: still standing at the end). */
export function laneStructures(feed: MatchFeed, lane: number): Record<LaneStructure, Record<Side, number | null>> {
  const fell = Object.fromEntries(
    LANE_STRUCTURES.map((kind) => [kind, { home: null, away: null }])
  ) as Record<LaneStructure, Record<Side, number | null>>;
  for (const objective of feed.objectives) {
    const { kind, lane: of } = objectiveOf(objective.objective);
    if (of !== lane || !objective.owner || !(LANE_STRUCTURES as readonly string[]).includes(kind)) continue;
    fell[kind as LaneStructure][objective.owner] = objective.t;
  }
  return fell;
}

// ── A player's rivals ────────────────────────────────────────────────────────

export interface Rival {
  memberId: number;
  count: number;
}

const top = (ids: (number | null)[]): Rival | null => {
  const counts = new Map<number, number>();
  for (const id of ids) if (id != null) counts.set(id, (counts.get(id) ?? 0) + 1);
  let best: Rival | null = null;
  for (const [memberId, count] of counts) if (!best || count > best.count) best = { memberId, count };
  return best;
};

/** Who killed the player most (his nemesis) and whom he killed most. */
export const rivals = (feed: MatchFeed, memberId: number) => ({
  nemesis: top(feed.kills.filter((kill) => kill.victim === memberId).map((kill) => kill.killer)),
  victim: top(feed.kills.filter((kill) => kill.killer === memberId).map((kill) => kill.victim))
});

/** The facts a lobby first is counted on; `true` when fewer is better. */
export const LOBBY_STATS: Record<string, boolean> = {
  kills: false,
  assists: false,
  deaths: true,
  net_worth: false,
  last_hits: false,
  denies: false,
  player_damage: false,
  boss_damage: false,
  player_healing: false
};

/** The stats on which the player is first among everyone in the match (ties count for each). */
export function lobbyFirsts(player: DlPlayer, everyone: readonly DlPlayer[]): string[] {
  return Object.entries(LOBBY_STATS)
    .filter(([code, fewer]) => {
      const mine = player.stats[code];
      if (mine == null || (!fewer && mine <= 0)) return false;
      const values = everyone.map((other) => other.stats[code]).filter((value) => value != null);
      return mine === (fewer ? Math.min(...values) : Math.max(...values));
    })
    .map(([code]) => code);
}

/** A damage source name as one row: a weapon's crit line folds into the weapon. */
export const sourceKey = (source: string) => source.replace(/_crit$/, "");
