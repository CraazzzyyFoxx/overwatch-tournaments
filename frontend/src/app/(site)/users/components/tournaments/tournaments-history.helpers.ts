import type { EncounterWithUserStats, UserTournament } from "@/types/user.types";
import type { ScoreKind } from "@/components/match/cells";

/** League grouping key: the prefix before " | " in the tournament name. */
export const leagueKey = (t: UserTournament): string => t.name.split(" | ")[0];

/** Division label for a league entry: the suffix after " | " (falls back to the
 *  raw name when there is no separator). */
export const divisionLabel = (t: UserTournament): string => {
  const parts = t.name.split(" | ");
  return parts.length > 1 ? parts.slice(1).join(" | ") : t.name;
};

export type TournamentGroup = UserTournament | UserTournament[];

/**
 * Group consecutive league tournaments (those with `is_league` sharing the same
 * league-name prefix) into arrays; non-league tournaments remain standalone
 * entries. Input order is preserved, so a league's divisions stay contiguous
 * exactly as the API returns them.
 */
export const groupTournamentsByLeague = (tournaments: UserTournament[]): TournamentGroup[] => {
  const result: TournamentGroup[] = [];
  let currentLeague: UserTournament[] = [];
  let flag = "";

  tournaments.forEach((t) => {
    if (t.is_league) {
      const key = leagueKey(t);
      if (flag && flag !== key) {
        result.push(currentLeague);
        currentLeague = [];
      }
      flag = key;
      currentLeague.push(t);
    } else {
      if (currentLeague.length > 0) {
        result.push(currentLeague);
        currentLeague = [];
        flag = "";
      }
      result.push(t);
    }
  });

  if (currentLeague.length > 0) result.push(currentLeague);

  return result;
};

// ─── Master-detail (Event dossier) helpers ──────────────────────────────────────
// Pure, side-effect-free logic shared by the explorer container, list and
// dossier. Kept here (not in a component) so it stays unit-testable.

/** Entries covered by a list group as a flat array. */
export const groupEntries = (group: TournamentGroup): UserTournament[] =>
  Array.isArray(group) ? group : [group];

export const isLeagueGroup = (group: TournamentGroup): group is UserTournament[] => Array.isArray(group);

/** Stable selection/URL key for a group: the first entry's tournament id. */
export const groupRepId = (group: TournamentGroup): number => groupEntries(group)[0].id;

/** Every tournament id a group covers (a league group covers all its divisions). */
export const groupTournamentIds = (group: TournamentGroup): number[] =>
  groupEntries(group).map((t) => t.id);

/** Display name: the league prefix for leagues, the tournament name otherwise. */
export const groupDisplayName = (group: TournamentGroup): string =>
  isLeagueGroup(group) ? leagueKey(group[0]) : group.name;

/** Best (lowest) placement across a group's entries; null when none recorded. */
export const groupBestPlacement = (group: TournamentGroup): number | null => {
  const placements = groupEntries(group)
    .map((t) => t.placement)
    .filter((p): p is number => typeof p === "number" && p > 0);
  return placements.length ? Math.min(...placements) : null;
};

/** Greatest tournament number in a group — used for "most recent" default + sort. */
export const groupMaxNumber = (group: TournamentGroup): number =>
  Math.max(...groupEntries(group).map((t) => t.number ?? 0), 0);

/** Aggregate W-D-L + map tallies across a group's entries. */
export interface GroupAggregate {
  won: number;
  lost: number;
  draw: number;
  mapsWon: number;
  mapsLost: number;
}
export const groupAggregate = (group: TournamentGroup): GroupAggregate =>
  groupEntries(group).reduce<GroupAggregate>(
    (acc, t) => ({
      won: acc.won + (t.won ?? 0),
      lost: acc.lost + (t.lost ?? 0),
      draw: acc.draw + (t.draw ?? 0),
      mapsWon: acc.mapsWon + (t.maps_won ?? 0),
      mapsLost: acc.mapsLost + (t.maps_lost ?? 0),
    }),
    { won: 0, lost: 0, draw: 0, mapsWon: 0, mapsLost: 0 }
  );

export type PlacementMedal = "gold" | "silver" | "bronze" | "none";
export const placementMedal = (placement: number | null | undefined): PlacementMedal => {
  if (placement === 1) return "gold";
  if (placement === 2) return "silver";
  if (placement === 3) return "bronze";
  return "none";
};

/** Role → the `--aqt-*` colour token used for role icons/accents. */
export const roleColorVar = (role: string | null): string =>
  role === "Tank" ? "var(--aqt-tank)" : role === "Support" ? "var(--aqt-support)" : "var(--aqt-damage)";

/** Map winrate as a 0–100 percentage; null when the player played no maps. */
export const mapsWinratePct = (mapsWon: number, mapsLost: number): number | null => {
  const total = mapsWon + mapsLost;
  return total > 0 ? (mapsWon / total) * 100 : null;
};

/** Winrate → design-book quality colour (≥60 good, 50–59 mid, <50 bad). */
export const winrateColor = (pct: number | null): string => {
  if (pct == null) return "var(--aqt-fg)";
  if (pct >= 60) return "var(--aqt-emerald)";
  if (pct >= 50) return "var(--aqt-amber)";
  return "var(--aqt-rose)";
};

/** Was the profile user on the home side of this encounter? */
export const isUserHomeInEncounter = (
  enc: EncounterWithUserStats,
  teamId: number,
  selfUserId: number
): boolean => enc.home_team_id === teamId || (enc.home_team?.players ?? []).some((p) => p.user_id === selfUserId);

/** Series (encounter-level) result from the user's perspective. */
export const encounterResult = (enc: EncounterWithUserStats, userHome: boolean): ScoreKind => {
  const us = userHome ? enc.score.home : enc.score.away;
  const them = userHome ? enc.score.away : enc.score.home;
  return us > them ? "win" : us < them ? "loss" : "draw";
};

export interface StageGroup {
  key: string;
  name: string;
  encounters: EncounterWithUserStats[];
  won: number;
  lost: number;
  drawn: number;
}

/** Group a tournament's encounters by stage (first-seen order) with a per-stage
 *  W-D-L series record from the user's perspective. */
export const groupEncountersByStage = (t: UserTournament, selfUserId: number): StageGroup[] => {
  const order: string[] = [];
  const byKey = new Map<string, StageGroup>();
  for (const enc of t.encounters ?? []) {
    const name = enc.stage?.name ?? enc.stage_item?.name ?? enc.name ?? "—";
    const key = String(enc.stage?.id ?? name);
    let group = byKey.get(key);
    if (!group) {
      group = { key, name, encounters: [], won: 0, lost: 0, drawn: 0 };
      byKey.set(key, group);
      order.push(key);
    }
    group.encounters.push(enc);
    const result = encounterResult(enc, isUserHomeInEncounter(enc, t.team_id, selfUserId));
    if (result === "win") group.won += 1;
    else if (result === "loss") group.lost += 1;
    else group.drawn += 1;
  }
  return order.map((key) => byKey.get(key) as StageGroup);
};

/** Mean MVP placement across the user's matches in a tournament (impact rank →
 *  legacy performance), or null when nothing is recorded. */
export const avgMvpPlacement = (entries: UserTournament[]): number | null => {
  let sum = 0;
  let count = 0;
  for (const t of entries) {
    for (const enc of t.encounters ?? []) {
      for (const match of enc.matches ?? []) {
        const placement = match.impact_rank ?? match.performance ?? null;
        if (placement != null) {
          sum += placement;
          count += 1;
        }
      }
    }
  }
  return count > 0 ? sum / count : null;
};
