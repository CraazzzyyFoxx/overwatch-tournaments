import type { RoundGroup } from "@/lib/bracket/view";
import { isEncounterCompleted, isEncounterLive } from "@/lib/encounter/status";
import type { Encounter } from "@/types/encounter.types";
import type { Team } from "@/types/team.types";
import type { StageSummary, Standings, TournamentStatus } from "@/types/tournament.types";

// ---------------------------------------------------------------------------
// Which of the three compositions a tournament gets
// ---------------------------------------------------------------------------

export type OverviewVariant = "registration" | "live" | "completed";

/**
 * Exhaustive over `TournamentStatus` on purpose: a status added on the backend
 * then fails the build here instead of silently landing on a fallback branch.
 */
const VARIANT_BY_STATUS: Record<TournamentStatus, OverviewVariant> = {
  announcement: "registration",
  draft: "registration",
  registration: "registration",
  check_in: "registration",
  live: "live",
  playoffs: "live",
  completed: "completed",
  archived: "completed"
};

export function overviewVariant(status: TournamentStatus): OverviewVariant {
  return VARIANT_BY_STATUS[status];
}

/** Stage types with a bracket to draw, and with a standings table instead. */
export const ELIMINATION_TYPES: Record<string, true> = {
  single_elimination: true,
  double_elimination: true
};
export const GROUP_TYPES: Record<string, true> = { round_robin: true, swiss: true };

/**
 * How each stage type reads beside the organizer's own stage name. A registry
 * over the backend's vocabulary rather than a chain of ternaries — the reason
 * `CHIP_META` and `TOURNAMENT_STATUS_META` are registries — with existing keys,
 * so no new copy. `stage_type` is a free column, so an unlisted value renders
 * the name alone instead of a raw enum token.
 */
export const STAGE_TYPE_LABEL: Record<string, "common.roundRobin" | "common.swiss" | "bracket.singleElimination" | "bracket.doubleElimination"> = {
  round_robin: "common.roundRobin",
  swiss: "common.swiss",
  single_elimination: "bracket.singleElimination",
  double_elimination: "bracket.doubleElimination"
};

/**
 * The stage the overview draws: the one being played now, and after the
 * tournament ends the one that decided it.
 *
 * Unpublished stages are skipped the way the bracket skips them
 * (`isStageVisibleToViewer`), unless nothing is published at all — an organizer
 * previewing their own tournament still sees which stage is meant.
 *
 * A phase running parallel divisions has no single answer, so the lowest id
 * wins and every card below is titled with that stage's name; the Format card
 * above lists the whole wave.
 */
export function pickOverviewStage(
  stages: readonly StageSummary[],
  variant: OverviewVariant
): StageSummary | null {
  const ordered = [...stages].sort((left, right) => left.order - right.order || left.id - right.id);
  const visible = ordered.filter((stage) => stage.is_published || stage.is_completed);
  const pool = visible.length > 0 ? visible : ordered;
  if (pool.length === 0) return null;

  if (variant === "completed") {
    return (
      pool.filter((stage) => ELIMINATION_TYPES[stage.stage_type] === true).at(-1) ??
      pool.at(-1) ??
      null
    );
  }
  return (
    pool.find((stage) => stage.is_active) ??
    pool.find((stage) => !stage.is_completed) ??
    pool.at(-1) ??
    null
  );
}

/** The round the stage is on: the first with anything unfinished, else its last. */
export function currentRoundOf(groups: readonly RoundGroup[]): number | null {
  for (const group of groups) {
    if (group.matches.some((match) => !isEncounterCompleted(match))) return group.round;
  }
  return groups.at(-1)?.round ?? null;
}

/**
 * Up to four columns of the mini-bracket (§3 ⑥): the current round with a
 * neighbour on each side, plus the stage's decider when that window does not
 * already reach it — the wireframe's "R1 · R2 · LR3 · GRAND FINAL".
 */
export function pickRoundWindow(
  groups: readonly RoundGroup[],
  currentRound: number | null
): RoundGroup[] {
  if (groups.length <= 4) return [...groups];

  const index =
    currentRound === null ? -1 : groups.findIndex((group) => group.round === currentRound);
  const start = index < 0 ? groups.length - 3 : Math.max(0, Math.min(index - 1, groups.length - 3));
  const window = groups.slice(start, start + 3);
  const decider = groups[groups.length - 1];
  return window.includes(decider) ? window : [...window, decider];
}

/** The completed encounter that decided the bracket: highest positive round. */
export function findGrandFinal(
  encounters: readonly Encounter[],
  stageId: number
): Encounter | null {
  const played = encounters.filter(
    (encounter) =>
      encounter.stage_id === stageId && encounter.round > 0 && isEncounterCompleted(encounter)
  );
  return played.reduce<Encounter | null>(
    (best, encounter) => (best === null || encounter.round > best.round ? encounter : best),
    null
  );
}

/**
 * The lower-bracket final: the deepest negative round. Its loser is third in a
 * double elimination bracket (§5 of the plan's default decisions).
 */
export function findLowerFinal(
  encounters: readonly Encounter[],
  stageId: number
): Encounter | null {
  const played = encounters.filter(
    (encounter) =>
      encounter.stage_id === stageId && encounter.round < 0 && isEncounterCompleted(encounter)
  );
  return played.reduce<Encounter | null>(
    (best, encounter) => (best === null || encounter.round < best.round ? encounter : best),
    null
  );
}

export function winnerSide(encounter: Encounter): "home" | "away" | null {
  const home = encounter.score?.home ?? 0;
  const away = encounter.score?.away ?? 0;
  if (home === away) return null;
  return home > away ? "home" : "away";
}

/* `countRegistrationRoles` is gone: the split is the server's answer now
   (`RegistrationListResponse.role_counts`), because a tournament that hides its
   participants list sends no rows to count. See `RegistrationSummary`. */

/**
 * Calendar days the tournament spans, inclusive. UTC getters on both ends so
 * the number is the same during SSR and after hydration.
 */
export function tournamentDaySpan(start: Date | string, end: Date | string): number | null {
  const from = new Date(start);
  const to = new Date(end);
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return null;
  const days =
    Math.floor(
      (Date.UTC(to.getUTCFullYear(), to.getUTCMonth(), to.getUTCDate()) -
        Date.UTC(from.getUTCFullYear(), from.getUTCMonth(), from.getUTCDate())) /
        86_400_000
    ) + 1;
  return days > 0 ? days : null;
}

/** The champion's roster as one line — names only, the `#1234` is noise here (§3C). */
export function rosterBattletags(team: Team | null | undefined): string {
  const players = team?.players ?? [];
  return players
    .map((player) => player.name)
    .filter((name): name is string => typeof name === "string" && name.length > 0)
    .map((name) => name.split("#")[0])
    .join(" · ");
}

/**
 * The stage's standings split into the ladders they actually are.
 *
 * A group stage's `stage_item`s are independent tables, each ranking 1..N of
 * its own field. Merged into one list and sorted by `position` they interleave
 * into 1,1,2,2,… — a rank column that says nothing and rows that read as
 * unsorted. Same split key the bracket page builds its per-group panels on;
 * the label falls back to the team's group when `stage_item` was not expanded,
 * and to `null` (one unnamed ladder) when neither is there.
 */
export function splitStandingsByGroup(
  rows: readonly Standings[]
): { key: string; name: string | null; rows: Standings[] }[] {
  const groups = new Map<string, { key: string; name: string | null; rows: Standings[] }>();
  for (const row of rows) {
    const key = String(row.stage_item_id ?? "stage");
    const group = groups.get(key) ?? {
      key,
      name: row.stage_item?.name ?? row.team?.group?.name ?? null,
      rows: []
    };
    group.rows.push(row);
    groups.set(key, group);
  }
  return [...groups.values()]
    .sort((left, right) => (left.name ?? "").localeCompare(right.name ?? ""))
    .map((group) => ({
      ...group,
      rows: [...group.rows].sort((left, right) => left.position - right.position)
    }));
}

/**
 * The four match lists the "now" block chooses between (⑤): what is being
 * played, what is next on the clock, what was last decided, and what has been
 * drawn but never scheduled.
 */
export type OverviewMatchLists = {
  live: Encounter[];
  upcoming: Encounter[];
  recent: Encounter[];
  pending: Encounter[];
};

export function selectOverviewMatchLists(
  encounters: readonly Encounter[],
  clockNow: number | null
): OverviewMatchLists {
  const live = encounters.filter(isEncounterLive);
  const upcoming = encounters
    .filter((encounter) => {
      if (isEncounterCompleted(encounter) || isEncounterLive(encounter)) return false;
      if (encounter.scheduled_at === null) return false;
      const at = new Date(encounter.scheduled_at).getTime();
      if (!Number.isFinite(at)) return false;
      // `clockNow` is null until hydration. Reading the wall clock here instead
      // would be a different instant on the server than in the browser, so the
      // pre-hydration pass keeps every scheduled match and the first client
      // render drops the ones that have already come round.
      return clockNow === null || at > clockNow;
    })
    .sort(
      (left, right) =>
        new Date(left.scheduled_at ?? 0).getTime() - new Date(right.scheduled_at ?? 0).getTime()
    )
    .slice(0, 4);
  const recent = encounters
    .filter(isEncounterCompleted)
    .sort((left, right) => {
      const leftAt = new Date(left.ended_at ?? left.scheduled_at ?? left.created_at).getTime();
      const rightAt = new Date(right.ended_at ?? right.scheduled_at ?? right.created_at).getTime();
      if (leftAt !== rightAt) return rightAt - leftAt;
      return right.id - left.id;
    })
    .slice(0, 4);
  // Drawn, but nobody has given it a time yet: a generated round sits here
  // until it is scheduled or played. Without this rung the overview claims
  // nothing is published while the bracket page shows a full grid.
  const pending = encounters
    .filter((encounter) => !isEncounterCompleted(encounter) && !isEncounterLive(encounter))
    .sort((left, right) => {
      if (left.round !== right.round) return Math.abs(left.round) - Math.abs(right.round);
      return left.id - right.id;
    })
    .slice(0, 4);

  return { live, upcoming, recent, pending };
}
