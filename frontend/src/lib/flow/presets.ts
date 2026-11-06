import type { FlowRead } from "@/types/flow.types";

import { addNode, connect, removeEdge, updateNode, type FlowDraft, type NewNode } from "./flowDraft";
import { kindOf, type FlowStageCreate } from "./kinds";

export type PresetId = "single" | "groups_playoff" | "groups_reformation_playoff" | "swiss_draft_playoff" | "league";

/** The order the preset dialog lists them in. */
export const PRESET_IDS: readonly PresetId[] = [
  "single",
  "groups_playoff",
  "groups_reformation_playoff",
  "swiss_draft_playoff",
  "league"
];

/** Node names are public ("Register for Day 3"), so the caller supplies them translated. */
export type PresetLabels = {
  playoff: string;
  groups: string;
  topPerGroup: (n: number) => string;
  top: (n: number) => string;
  playoffTeams: string;
  swiss: string;
  qualifiers: string;
  day: (i: number) => string;
  dayTeams: (i: number) => string;
  season: string;
  seasonTable: string;
};

const COL = 260;
const ROW = 160;

/** Presets are offered while the flow is just the starter registration → formation pair, untouched. */
export const hasOnlyStarterNodes = (read: FlowRead): boolean =>
  read.nodes.every((n) => ["registration", "formation"].includes(kindOf(n)) && `${n.status}` === "draft") &&
  ["registration", "formation"].every((k) => read.nodes.some((n) => kindOf(n) === k));

export function applyPreset(
  draft: FlowDraft,
  preset: PresetId,
  { days = 3, best = 2 }: { days?: number; best?: number },
  labels: PresetLabels
): FlowDraft {
  const registration = draft.nodes.find((n) => n.kind === "registration");
  const formation = draft.nodes.find((n) => n.kind === "formation");
  if (!registration || !formation) throw new Error("preset needs the starter registration and formation");
  if (preset === "league" && (!Number.isInteger(days) || days < 2 || days > 10 || best < 1 || best > days)) {
    throw new RangeError(`league needs 2..10 days and 1..days counted, got ${days} days, best ${best}`);
  }

  let d = draft;
  const at = (col: number, row = 0) => ({ x: col * COL, y: row * ROW });
  const add = (node: NewNode) => {
    const key = `new-${d.nextRef}`;
    d = addNode(d, node);
    return key;
  };
  // Wired after every node is added, so new node keys are `new-1…new-n` and edge keys follow.
  const wired: Parameters<typeof connect>[1][] = [];
  const wire = (source: string, sourceHandle: string, target: string, targetHandle: string) => {
    wired.push({ source, sourceHandle, target, targetHandle });
  };
  const stage = (name: string, stageType: FlowStageCreate["stage_type"], col: number, row = 0, extra: Partial<FlowStageCreate> = {}) =>
    add({ kind: "stage", name, config: {}, stage: { name, stage_type: stageType, order: col, ...extra }, ...at(col, row) });
  const filter = (name: string, config: Record<string, unknown>, col: number) =>
    add({ kind: "filter", name, config, ...at(col) });
  const playoff = (col: number, extra: Partial<FlowStageCreate> = {}) =>
    stage(labels.playoff, "single_elimination", col, 0, extra);
  const formed = (name: string, col: number, row = 0) =>
    add({ kind: "formation", name, config: { mode: formation.config.mode }, ...at(col, row) });

  if (preset === "single") {
    wire(formation.key, "teams", playoff(2), "participants");
  } else if (preset === "groups_playoff") {
    const groups = stage(labels.groups, "round_robin", 2);
    const cut = filter(labels.topPerGroup(2), { mode: "per_item_top", n: 2 }, 3);
    wire(formation.key, "teams", groups, "participants");
    wire(groups, "ranking", cut, "ranking");
    wire(cut, "passed", playoff(4, { seed_ranking: "cross" }), "participants");
  } else if (preset === "groups_reformation_playoff") {
    const groups = stage(labels.groups, "round_robin", 2);
    const cut = filter(labels.top(4), { mode: "top", n: 4 }, 3);
    const teams = formed(labels.playoffTeams, 4);
    wire(formation.key, "teams", groups, "participants");
    wire(groups, "ranking", cut, "ranking");
    wire(cut, "passed", teams, "players");
    wire(teams, "teams", playoff(5), "participants");
  } else if (preset === "swiss_draft_playoff") {
    const starterEdge = d.edges.find((e) => e.source === registration.key && e.target === formation.key);
    if (starterEdge) d = removeEdge(d, starterEdge.key);
    const swiss = stage(labels.swiss, "individual_swiss", 1, 0, { playoff_team_count: 4 });
    const cut = filter(labels.qualifiers, { mode: "top", n: 20 }, 2);
    d = updateNode(d, formation.key, { x: 3 * COL, config: { ...formation.config, mode: "draft" } });
    wire(registration.key, "participants", swiss, "participants");
    wire(swiss, "ranking", cut, "ranking");
    wire(cut, "passed", formation.key, "players");
    wire(formation.key, "teams", playoff(4), "participants");
  } else {
    const middle = Math.floor((days - 1) / 2);
    const dayStages: string[] = [];
    for (let i = 1; i <= days; i++) {
      const row = i - 1;
      let teams = formation.key;
      if (i === 1) {
        d = updateNode(d, registration.key, { name: labels.day(1) });
        d = updateNode(d, formation.key, { name: labels.dayTeams(1) });
      } else {
        const intake = add({ kind: "registration", name: labels.day(i), config: {}, ...at(0, row) });
        teams = formed(labels.dayTeams(i), 1, row);
        wire(intake, "participants", teams, "players");
      }
      const dayStage = stage(labels.day(i), "round_robin", 2, row);
      wire(teams, "teams", dayStage, "participants");
      dayStages.push(dayStage);
    }
    const counted = best < days;
    const season = add({
      kind: "aggregate",
      name: labels.season,
      config: {
        unit: "players",
        score: { preset: "stage_points" },
        mode: counted ? "sum_best_n" : "sum_all",
        n: counted ? best : null
      },
      ...at(3, middle)
    });
    const table = add({ kind: "leaderboard", name: labels.seasonTable, config: {}, ...at(4, middle) });
    for (const dayStage of dayStages) wire(dayStage, "ranking", season, "inputs");
    wire(season, "ranking", table, "ranking");
  }
  return wired.reduce((acc, c) => connect(acc, c), d);
}
