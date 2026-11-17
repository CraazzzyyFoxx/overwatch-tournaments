import type { LinkTabItem } from "@/components/kit/LinkTabs";
import {
  FFA_STAGE_TYPES,
  GROUP_STAGE_TYPES,
  INDIVIDUAL_SWISS_STAGE_TYPES
} from "@/lib/bracket/projection";
import { tournamentHref } from "@/lib/tournament/url";
import type { Encounter } from "@/types/encounter.types";
import type { Stage, StageItem, Standings, Tournament } from "@/types/tournament.types";

/** FFA and individual Swiss: one panel per STAGE, never per group item. */
const isWholeStagePanel = (stage: Stage) =>
  FFA_STAGE_TYPES.includes(stage.stage_type) ||
  INDIVIDUAL_SWISS_STAGE_TYPES.includes(stage.stage_type);

/**
 * A stage's phase is its `order`: the flow editor keeps it at 1 + the phase of the stages that feed it, and parallel
 * stages (legacy group stages, divisions) share one. Qualification → groups → playoff are three phases, not one group scope.
 */
const phaseOf = (stage: Stage) => stage.order ?? 0;

/** Which stages the bracket screen is currently drawing, and in which mode. */
export type BracketStageSelection = {
  groupStages: Stage[];
  eliminationStages: Stage[];
  /** `true` when the group-scope panels are on screen instead of a bracket. */
  shouldShowGroupStage: boolean;
  activeGroupStages: Stage[];
  activeStages: Stage[];
};

/**
 * The stage split the whole screen keys on.
 *
 * An FFA league joins the "group scope": it has no pairings, so it is never a
 * bracket, and its tab, its stage selection and its per-group panels follow
 * exactly the same route as a round robin's. Only the PANEL differs.
 */
export function selectBracketStages(
  stages: readonly Stage[],
  viewParam: string | null,
  /** Already resolved by `createBracketQueryPlan`, default stage included. */
  stageId: number | null
): BracketStageSelection {
  const groupStages = stages.filter(
    (stage) =>
      GROUP_STAGE_TYPES.includes(stage.stage_type) || isWholeStagePanel(stage)
  );
  const eliminationStages = stages.filter(
    (stage) =>
      stage.stage_type === "single_elimination" || stage.stage_type === "double_elimination"
  );

  const primaryStage = stages.find((stage) => stage.id === stageId);
  const shouldShowGroupStage =
    viewParam === "groups" ||
    (primaryStage ? groupStages.some((stage) => stage.id === primaryStage.id) : false);
  // The dedicated groups view lists every group stage of the selected stage's phase; arriving on a group
  // stage by any other route shows only that one.
  const phaseStages =
    primaryStage && groupStages.some((stage) => stage.id === primaryStage.id)
      ? groupStages.filter((stage) => phaseOf(stage) === phaseOf(primaryStage))
      : groupStages;
  const activeGroupStages =
    shouldShowGroupStage && viewParam === "groups"
      ? phaseStages
      : shouldShowGroupStage && primaryStage
        ? [primaryStage]
        : [];

  return {
    groupStages,
    eliminationStages,
    shouldShowGroupStage,
    activeGroupStages,
    activeStages: shouldShowGroupStage ? activeGroupStages : primaryStage ? [primaryStage] : []
  };
}

export type GroupStagePanelData = {
  key: string;
  stage: Stage;
  stageItem: StageItem | undefined;
  encounters: Encounter[];
  standings: Standings[];
};

/** One panel per group, per stage — except FFA, which is one panel per STAGE. */
export function buildGroupStagePanels(
  activeGroupStages: readonly Stage[],
  encounters: readonly Encounter[],
  standings: readonly Standings[]
): GroupStagePanelData[] {
  return activeGroupStages.flatMap((stage): GroupStagePanelData[] => {
    // One panel per FFA STAGE, not per group: `FfaStagePanel` reads every
    // lobby of the stage in a single request and renders a table per lobby,
    // so splitting by item here would repeat that request per group.
    if (isWholeStagePanel(stage)) {
      return [{ key: `stage-${stage.id}`, stage, stageItem: undefined, encounters: [], standings: [] }];
    }

    if (stage.items.length === 0) {
      return [
        {
          key: `stage-${stage.id}`,
          stage,
          stageItem: undefined,
          encounters: encounters.filter((encounter) => encounter.stage_id === stage.id),
          standings: standings.filter((standing) => standing.stage_id === stage.id)
        }
      ];
    }

    return stage.items.map((stageItem) => ({
      key: `stage-${stage.id}-item-${stageItem.id}`,
      stage,
      stageItem,
      encounters: encounters.filter(
        (encounter) =>
          encounter.stage_id === stage.id && encounter.stage_item_id === stageItem.id
      ),
      standings: standings.filter(
        (standing) => standing.stage_id === stage.id && standing.stage_item_id === stageItem.id
      )
    }));
  });
}

/** The stage rail: its links, and the key of the one being viewed ("" for none). */
export type BracketTabs = { items: LinkTabItem[]; activeKey: string };

type BracketTabsInput = {
  tournament: Tournament;
  groupStages: readonly Stage[];
  eliminationStages: readonly Stage[];
  activeStageId: number | undefined;
  viewParam: string | null;
  /** Until the encounter list resolves, nothing is disabled. */
  matchCountsKnown: boolean;
  stageIdsWithMatches: ReadonlySet<number | null>;
  labels: { groupStage: string; playoff: string };
};

/**
 * The stage rail. The encounters query pulls the whole tournament, not just the
 * selected stage, so it also answers "does that other tab lead anywhere?" —
 * a tab that flickers inert is worse than a tab that lands on an empty state,
 * which is why `matchCountsKnown` gates the disabling.
 */
export function buildBracketTabs({
  tournament,
  groupStages,
  eliminationStages,
  activeStageId,
  viewParam,
  matchCountsKnown,
  stageIdsWithMatches,
  labels
}: BracketTabsInput): BracketTabs {
  const tabs: LinkTabItem[] = [];
  let activeKey = "";

  // An FFA or individual Swiss stage is ONE scope however many groups it has: its panel renders
  // every lobby of the stage at once, so its groups are not separate tabs.
  const scopeCount = (phase: readonly Stage[]) =>
    phase.reduce(
      (count, stage) => count + (isWholeStagePanel(stage) ? 1 : Math.max(stage.items.length, 1)),
      0
    );
  const wholeStageIds = new Set(groupStages.filter(isWholeStagePanel).map((stage) => stage.id));

  // The tab you are standing on stays live even when empty; you are already
  // looking at its empty state. A group stage has its table to show as soon as
  // teams are seeded, before any match is played, and an FFA stage never appears
  // in the encounter list this counts — that list answers duels — so neither is
  // judged on matches alone. An unfinished bracket with no matches draws the one
  // the generator would build; only a finished one with none has nothing.
  const groupHasContent = (stage: Stage) =>
    stageIdsWithMatches.has(stage.id) ||
    wholeStageIds.has(stage.id) ||
    stage.items.some((item) => item.inputs.length > 0);
  const isDead = (isActive: boolean, hasContent: boolean) =>
    !isActive && matchCountsKnown && !hasContent;

  // One tab per phase, in phase order: the group stages of a phase share a tab, every bracket keeps its own.
  const groupPhases = new Map<number, Stage[]>();
  for (const stage of groupStages)
    groupPhases.set(phaseOf(stage), [...(groupPhases.get(phaseOf(stage)) ?? []), stage]);
  const phases = [
    ...[...groupPhases.entries()].map(([order, stages]) => ({ order, stages, bracket: false })),
    ...eliminationStages.map((stage) => ({ order: phaseOf(stage), stages: [stage], bracket: true }))
  ].sort((a, b) => a.order - b.order);

  for (const { order, stages, bracket } of phases) {
    const first = stages[0];
    if (bracket) {
      const isActive = !viewParam && first.id === activeStageId;
      if (isActive) activeKey = `stage-${first.id}`;
      tabs.push({
        key: `stage-${first.id}`,
        href: tournamentHref(tournament, `/bracket?stage=${first.id}`),
        label:
          eliminationStages.length === 1 && groupStages.length > 0 ? labels.playoff : first.name,
        disabled: isDead(isActive, stageIdsWithMatches.has(first.id) || first.status !== "completed")
      });
      continue;
    }
    const key = stages.length === 1 ? `stage-${first.id}` : `group-stage-${order}`;
    const isActive = !!activeStageId && stages.some((stage) => stage.id === activeStageId);
    if (isActive) activeKey = key;
    tabs.push({
      key,
      href:
        stages.length === 1
          ? tournamentHref(tournament, `/bracket?stage=${first.id}`)
          : tournamentHref(tournament, `/bracket?view=groups&stage=${first.id}`),
      // The generic "Group stage" names the one group phase of a groups → playoff tournament; with several
      // phases each tab says which stage it is.
      label:
        groupPhases.size === 1 && scopeCount(stages) > 1
          ? labels.groupStage
          : stages.map((stage) => stage.name).join(" · "),
      disabled: isDead(isActive, stages.some(groupHasContent))
    });
  }

  return { items: tabs, activeKey };
}
