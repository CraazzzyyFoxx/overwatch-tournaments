import type { SegmentedLinkItem } from "@/components/ui/segmented";
import { FFA_STAGE_TYPES, GROUP_STAGE_TYPES } from "@/lib/bracket/projection";
import { tournamentHref } from "@/lib/tournament/url";
import type { Encounter } from "@/types/encounter.types";
import type { Stage, StageItem, Standings, Tournament } from "@/types/tournament.types";

/** Which stages the bracket screen is currently drawing, and in which mode. */
export type BracketStageSelection = {
  groupStages: Stage[];
  eliminationStages: Stage[];
  /** What the screen falls back to when `?stage=` names nothing available. */
  fallbackStage: Stage | undefined;
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
  requestedStageId: number | null
): BracketStageSelection {
  const groupStages = stages.filter(
    (stage) =>
      GROUP_STAGE_TYPES.includes(stage.stage_type) || FFA_STAGE_TYPES.includes(stage.stage_type)
  );
  const eliminationStages = stages.filter(
    (stage) =>
      stage.stage_type === "single_elimination" || stage.stage_type === "double_elimination"
  );

  const activeStage = stages.find((stage) => stage.is_active);
  const fallbackStage = activeStage ?? eliminationStages[0] ?? stages[0];
  const requestedStage = stages.find((stage) => stage.id === requestedStageId);
  const primaryStage = requestedStage ?? fallbackStage;
  const shouldShowGroupStage =
    viewParam === "groups" ||
    (primaryStage ? groupStages.some((stage) => stage.id === primaryStage.id) : false);
  // The dedicated groups view lists every group stage; arriving on a group
  // stage by any other route shows only that one.
  const activeGroupStages =
    shouldShowGroupStage && viewParam === "groups"
      ? groupStages
      : shouldShowGroupStage && primaryStage
        ? [primaryStage]
        : [];

  return {
    groupStages,
    eliminationStages,
    fallbackStage,
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
    if (FFA_STAGE_TYPES.includes(stage.stage_type)) {
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
}: BracketTabsInput): SegmentedLinkItem[] {
  const tabs: SegmentedLinkItem[] = [];

  // An FFA stage is ONE scope however many groups it has: its panel renders
  // every lobby of the stage at once, so its groups are not separate tabs.
  const groupScopeCount = groupStages.reduce(
    (count, stage) =>
      count + (FFA_STAGE_TYPES.includes(stage.stage_type) ? 1 : Math.max(stage.items.length, 1)),
    0
  );
  const ffaStageIds = new Set(
    groupStages
      .filter((stage) => FFA_STAGE_TYPES.includes(stage.stage_type))
      .map((stage) => stage.id)
  );

  const isGroupViewActive =
    viewParam === "groups" ||
    (!!activeStageId && groupStages.some((stage) => stage.id === activeStageId));

  // The tab you are standing on stays live even when empty; you are already
  // looking at its empty state. An FFA stage never appears in the encounter
  // list this counts — that list answers duels — so its tab is judged on the
  // stage existing, not on matches nobody asked for.
  const isDead = (isActive: boolean, stageIds: readonly number[]) =>
    !isActive &&
    matchCountsKnown &&
    !stageIds.some((id) => stageIdsWithMatches.has(id) || ffaStageIds.has(id));

  if (groupScopeCount > 1) {
    tabs.push({
      key: "group-stage",
      href:
        groupStages.length === 1
          ? tournamentHref(tournament, `/bracket?stage=${groupStages[0].id}`)
          : tournamentHref(tournament, "/bracket?view=groups"),
      label: labels.groupStage,
      isActive: isGroupViewActive,
      disabled: isDead(
        isGroupViewActive,
        groupStages.map((stage) => stage.id)
      )
    });
  } else if (groupStages.length === 1) {
    const stage = groupStages[0];
    const isActive = !viewParam && stage.id === activeStageId;
    tabs.push({
      key: `stage-${stage.id}`,
      href: tournamentHref(tournament, `/bracket?stage=${stage.id}`),
      label: stage.name,
      isActive,
      disabled: isDead(isActive, [stage.id])
    });
  }

  for (const stage of eliminationStages) {
    const isActive = !viewParam && stage.id === activeStageId;
    tabs.push({
      key: `stage-${stage.id}`,
      href: tournamentHref(tournament, `/bracket?stage=${stage.id}`),
      label:
        eliminationStages.length === 1 && groupStages.length > 0 ? labels.playoff : stage.name,
      isActive,
      disabled: isDead(isActive, [stage.id])
    });
  }

  return tabs;
}
