import type { BracketRoundLabelFormatter } from "@/hooks/useBracketRoundLabel";
import {
  bracketRoundShape,
  buildRoundGroups,
  orderEliminationRounds,
  type RoundGroup
} from "@/lib/bracket/view";
import { isEncounterCompleted, isEncounterLive } from "@/lib/encounter/status";
import type { Encounter } from "@/types/encounter.types";
import type { StageType, Tournament } from "@/types/tournament.types";

export const MATCHES_VIEWS = ["round", "time"] as const;
export type MatchesView = (typeof MATCHES_VIEWS)[number];

/** Stage types whose rounds are named and numbered by the bracket rather than by group. */
const IS_ELIMINATION: Record<string, true> = {
  single_elimination: true,
  double_elimination: true
};

export function toDate(value: Date | string | null | undefined): Date | null {
  if (value == null) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** When a match happens, as the time view understands it: the plan first, then the record. */
function encounterInstant(encounter: Encounter): Date | null {
  return toDate(encounter.scheduled_at) ?? toDate(encounter.ended_at);
}

/** Local calendar day, so two matches an hour apart across midnight land on different days. */
function dayKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
}

/** A stage chip's URL value. `null` is a real bucket (a scrim-shaped encounter), not "all". */
export function stageKey(stageId: number | null): string {
  return stageId === null ? "none" : String(stageId);
}

/** Whether a stage type draws a bracket, so its rounds carry match numbers. */
export function isEliminationStageType(type: StageType | undefined): boolean {
  return IS_ELIMINATION[type ?? ""] === true;
}

export type StageMeta = {
  id: number | null;
  name: string;
  order: number;
  type: StageType | undefined;
};

/**
 * The stages that actually carry encounters, last stage first.
 *
 * `tournament.stages` is the source of names and order; a `stage_id` the
 * overview does not carry (a stage created after this page's tournament read)
 * still gets a bucket from the encounter's own `stage` relation, so no match
 * disappears from the chips.
 */
export function collectStages(encounters: Encounter[], tournament: Tournament): StageMeta[] {
  const byId = new Map<number | null, StageMeta>();
  for (const encounter of encounters) {
    if (byId.has(encounter.stage_id)) continue;
    const summary =
      tournament.stages.find((stage) => stage.id === encounter.stage_id) ?? encounter.stage ?? null;
    byId.set(encounter.stage_id, {
      id: encounter.stage_id,
      name: summary?.name ?? "",
      order: summary?.order ?? -1,
      type: summary?.stage_type
    });
  }
  return [...byId.values()].sort((left, right) => right.order - left.order);
}

export type MatchListRow = {
  encounter: Encounter;
  leading: string;
  trailing?: string;
};

export type MatchBlock = {
  key: string;
  /** Mono heading, already joined with " · ". */
  heading: string;
  rows: MatchListRow[];
};

/**
 * One stage's rounds in reading order — final first — with the leading and
 * trailing mono cells of every row.
 *
 * Elimination stages come from `orderEliminationRounds` reversed: the
 * bracket's own match numbering is the only thing that knows the lower final
 * (round -4) is played before the grand final (round 3).
 */
export function buildStageBlocks(
  stage: StageMeta,
  encounters: Encounter[],
  roundLabel: BracketRoundLabelFormatter,
  countLabel: (count: number) => string
): MatchBlock[] {
  const isElimination = isEliminationStageType(stage.type);
  const byId = new Map(encounters.map((encounter) => [encounter.id, encounter]));

  let groups: RoundGroup[];
  let matchNumbers = new Map<number, number>();
  const shape = bracketRoundShape(isElimination ? stage.type : undefined, encounters);

  if (isElimination) {
    const order = orderEliminationRounds(encounters, stage.type);
    groups = [...order.groups].reverse();
    matchNumbers = order.matchNumbers;
  } else {
    groups = buildRoundGroups(encounters).sort((left, right) => right.round - left.round);
  }

  return groups.map((group) => {
    const rows: MatchListRow[] = [];
    for (const match of group.matches) {
      const encounter = byId.get(match.id);
      if (!encounter) continue;
      const bo = `Bo${encounter.best_of}`;
      if (isElimination) {
        const number = matchNumbers.get(encounter.id);
        // The group heading already names the round, so a trailing cell would
        // only repeat it — wireframe §7: playoff rows carry no trailing text.
        rows.push({ encounter, leading: number == null ? bo : `M${number} · ${bo}` });
        continue;
      }
      // Wireframe §7 ⑥: the group letter leads, the format trails. The round is
      // in the heading and the group is already the leading cell, so the
      // trailing cell says only what neither of them does.
      rows.push({ encounter, leading: encounter.stage_item?.name ?? bo, trailing: bo });
    }

    return {
      key: `${stageKey(stage.id)}:${group.round}`,
      heading: [
        stage.name,
        roundLabel(group.round, shape),
        rows.length > 1 ? countLabel(rows.length) : null
      ]
        .filter(Boolean)
        .join(" · "),
      rows
    };
  });
}

type DatedEncounter = { encounter: Encounter; at: Date };

export type TimeSections = {
  live: Encounter[];
  /** Day blocks in reading order: today's remaining matches, later days, then played days. */
  days: MatchBlock[];
};

/**
 * The time view's sections: what is on air, what is still to come, then the
 * record by day.
 *
 * Note §7 ④ asks for the stage name in the day heading "from `phase_schedule`
 * when the day falls inside a phase". `phase_schedule` carries lifecycle phases
 * (registration / check-in / draft / live), never stage names — so the stage
 * comes from the day's own encounters when they unanimously share one, and the
 * phase is the fallback for a day whose matches carry no stage at all.
 *
 * The wireframe shows only "later today" ahead of the played days. Days further
 * out get their own section here rather than being dropped: a schedule
 * published a week ahead is the very data this view exists for.
 */
export function buildTimeSections(
  encounters: Encounter[],
  now: Date,
  labels: {
    day: (date: Date) => string;
    time: (date: Date) => string;
    laterToday: string;
    unscheduled: string;
    phase: (date: Date) => string | null;
    trailing: (encounter: Encounter) => string | undefined;
    count: (count: number) => string;
  }
): TimeSections {
  const live: Encounter[] = [];
  const upcoming = new Map<string, DatedEncounter[]>();
  const past = new Map<string, DatedEncounter[]>();
  const undated: Encounter[] = [];
  const today = dayKey(now);

  for (const encounter of encounters) {
    if (isEncounterLive(encounter)) {
      live.push(encounter);
      continue;
    }
    const at = encounterInstant(encounter);
    if (at === null) {
      undated.push(encounter);
      continue;
    }
    const ahead = !isEncounterCompleted(encounter) && at.getTime() > now.getTime();
    const bucket = ahead ? upcoming : past;
    const key = dayKey(at);
    const existing = bucket.get(key);
    if (existing) existing.push({ encounter, at });
    else bucket.set(key, [{ encounter, at }]);
  }

  const toBlock = (key: string, dated: DatedEncounter[], ascending: boolean): MatchBlock => {
    const ordered = [...dated].sort((left, right) =>
      ascending ? left.at.getTime() - right.at.getTime() : right.at.getTime() - left.at.getTime()
    );
    const stageIds = new Set(ordered.map((row) => row.encounter.stage_id));
    const unanimousStage =
      stageIds.size === 1 ? ordered[0].encounter.stage?.name ?? null : null;
    const date = ordered[0].at;
    return {
      key,
      heading: [
        key === today && ordered.some((row) => !isEncounterCompleted(row.encounter))
          ? `${labels.laterToday} · ${labels.day(date)}`
          : labels.day(date),
        unanimousStage ?? labels.phase(date),
        ordered.length > 1 ? labels.count(ordered.length) : null
      ]
        .filter(Boolean)
        .join(" · "),
      rows: ordered.map((row) => ({
        encounter: row.encounter,
        leading: labels.time(row.at),
        trailing: labels.trailing(row.encounter)
      }))
    };
  };

  const days: MatchBlock[] = [
    ...[...upcoming.entries()]
      .sort((left, right) => left[1][0].at.getTime() - right[1][0].at.getTime())
      .map(([key, dated]) => toBlock(key, dated, true)),
    ...[...past.entries()]
      .sort((left, right) => right[1][0].at.getTime() - left[1][0].at.getTime())
      .map(([key, dated]) => toBlock(key, dated, false))
  ];

  if (undated.length > 0) {
    days.push({
      key: "undated",
      heading: [labels.unscheduled, labels.count(undated.length)].join(" · "),
      rows: undated.map((encounter) => ({
        encounter,
        leading: "—",
        trailing: labels.trailing(encounter)
      }))
    });
  }

  return { live, days };
}
