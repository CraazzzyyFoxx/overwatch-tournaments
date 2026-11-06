import type { RoundGroup } from "@/lib/bracket/view";
import { getEncounterWinner, isEncounterCompleted } from "@/lib/encounter/status";
import { hasPlayStarted } from "@/lib/tournament/stages";
import { displayStatus, reachedCheckIn } from "@/lib/tournament/status";
import type { Encounter } from "@/types/encounter.types";
import type { Registration } from "@/types/registration.types";
import type { Team } from "@/types/team.types";
import type { StageSummary, Standings, Tournament } from "@/types/tournament.types";
import type { PersonDisplay } from "@/types/user.types";

// ---------------------------------------------------------------------------
// Which of the three compositions a tournament gets
// ---------------------------------------------------------------------------

export type OverviewVariant = "registration" | "live" | "completed";

/**
 * The overview a tournament gets: the finished one, the one once play has started, and the registration view for
 * everything before — announcing, signing up, checking in and forming the teams.
 */
export function overviewVariant(tournament: Pick<Tournament, "status" | "stages">): OverviewVariant {
  if (tournament.status === "completed" || tournament.status === "archived") return "completed";
  return hasPlayStarted(tournament.status, tournament.stages) ? "live" : "registration";
}

/**
 * Whether the field is set: teams exist and sign-ups are behind them. Until
 * then the overview's registration block owns the numbers (who signed up, how
 * the roles split); from then on the hero quotes "14 teams · 70 players" once
 * and the overview shows the teams themselves. A team-registration tournament
 * has teams during registration, and they are still sign-ups then.
 */
export function hasTeamLineup(
  tournament: Pick<Tournament, "status" | "flow_nodes" | "teams_count">
): boolean {
  return (tournament.teams_count ?? 0) > 0 && reachedCheckIn(displayStatus(tournament));
}

/** Stage types with a bracket to draw, and with a standings table instead. */
export const ELIMINATION_TYPES: Record<string, true> = {
  single_elimination: true,
  double_elimination: true
};
export const GROUP_TYPES: Record<string, true> = { round_robin: true, swiss: true };

/**
 * The stage formats the overview names and explains, each with its own
 * `tournamentDetail.overview.format.types.<format>` copy. `stage_type` is a
 * free column, so an unlisted value renders the name alone instead of a raw
 * enum token.
 */
const STAGE_FORMATS = [
  "round_robin",
  "swiss",
  "ffa_league",
  "individual_swiss",
  "single_elimination",
  "double_elimination"
] as const;
export type StageFormat = (typeof STAGE_FORMATS)[number];

export function stageFormatOf(stageType: string): StageFormat | null {
  return (STAGE_FORMATS as readonly string[]).includes(stageType)
    ? (stageType as StageFormat)
    : null;
}

/** One regulation fact of a stage, as the overview's "How it's played" words it. */
export type StageFact =
  | { kind: "rounds"; count: number }
  | { kind: "bestOf"; n: number }
  | { kind: "finalBestOf"; n: number }
  | { kind: "qualify"; count: number }
  | { kind: "eliminate"; count: number }
  | { kind: "grandFinal"; reset: boolean };

/**
 * What a reader needs to follow a stage, read off its regulation: how long it
 * runs, how long a series is, how a team gets through. Only what applies — an
 * FFA lobby plays no series.
 */
export function stageFacts(stage: StageSummary): StageFact[] {
  const facts: StageFact[] = [];
  const isFfa = stage.stage_type === "ffa_league";
  if ((stage.stage_type === "swiss" || isFfa) && stage.max_rounds > 0) {
    facts.push({ kind: "rounds", count: stage.max_rounds });
  }
  if (!isFfa && stage.best_of.default > 0) facts.push({ kind: "bestOf", n: stage.best_of.default });
  if (
    ELIMINATION_TYPES[stage.stage_type] === true &&
    stage.best_of.final != null &&
    stage.best_of.final !== stage.best_of.default
  ) {
    facts.push({ kind: "finalBestOf", n: stage.best_of.final });
  }
  if (stage.stage_type === "swiss") {
    if (stage.swiss_qualify_wins != null)
      facts.push({ kind: "qualify", count: stage.swiss_qualify_wins });
    if (stage.swiss_eliminate_losses != null) {
      facts.push({ kind: "eliminate", count: stage.swiss_eliminate_losses });
    }
  }
  if (stage.stage_type === "double_elimination") {
    facts.push({ kind: "grandFinal", reset: stage.de_grand_final_type === "with_reset" });
  }
  return facts;
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

/** A registration's name for a list row: "—" for one with no game handle and no account. */
export function registrationDisplay({ display }: Pick<Registration, "display">): PersonDisplay {
  return display.name ? display : { ...display, name: "—" };
}

/** The champion's roster as one line — names only, the `#1234` is noise here (§3C). */
export function rosterNames(team: Team | null | undefined): string {
  return (team?.players ?? [])
    .map((player) => player.display.name)
    .filter((name) => name.length > 0)
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

export type GroupResult = "w" | "l" | "d";

/** One team's line in its group's live table. */
export interface GroupRow {
  teamId: number;
  team: Team | null;
  groupKey: string;
  groupName: string | null;
  position: number;
  points: number;
  /** Maps won minus maps lost over the finished series. */
  mapDiff: number;
  /** Finished series, oldest round first. */
  form: GroupResult[];
}

/**
 * The live group tables: places, order and points are the official standings' (tiebreakers included); the form and
 * the map difference come from the stage's finished series.
 */
export function buildGroupRows(
  stageStandings: readonly Standings[],
  stageEncounters: readonly Encounter[]
): GroupRow[] {
  const tally = new Map<
    number,
    { mapDiff: number; results: { round: number; result: GroupResult }[] }
  >();
  for (const encounter of stageEncounters) {
    if (!isEncounterCompleted(encounter)) continue;
    const winner = getEncounterWinner(encounter);
    for (const seat of encounter.teams) {
      const other = encounter.teams.find((item) => item !== seat);
      if (seat.team_id == null || !other) continue;
      const row = tally.get(seat.team_id) ?? { mapDiff: 0, results: [] };
      row.mapDiff += seat.score - other.score;
      row.results.push({
        round: encounter.round,
        result: winner == null ? "d" : winner === seat.slot ? "w" : "l"
      });
      tally.set(seat.team_id, row);
    }
  }
  return splitStandingsByGroup(stageStandings).flatMap((group) =>
    group.rows.map((row) => {
      const own = tally.get(row.team_id);
      return {
        teamId: row.team_id,
        team: row.team,
        groupKey: group.key,
        groupName: group.name,
        position: row.position,
        points: row.points,
        mapDiff: own?.mapDiff ?? 0,
        form: [...(own?.results ?? [])].sort((a, b) => a.round - b.round).map((item) => item.result)
      };
    })
  );
}
