"use client";

import { useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { ConnectionIndicator } from "@/components/realtime/ConnectionIndicator";
import { EncounterEditDialog } from "@/components/tournaments/EncounterEditDialog";
import { MatchReportDialog } from "@/components/tournaments/MatchReportDialog";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { isTournamentStatusEnded } from "@/lib/tournament/status";
import { useRealtimeStore } from "@/stores/realtime.store";
import { FFA_STAGE_TYPES } from "@/lib/bracket/projection";
import type { Tournament } from "@/types/tournament.types";
import type { Encounter } from "@/types/encounter.types";

import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentBracketSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { useTournamentStreamsQuery } from "../_hooks/useTournamentStreams";
import styles from "../TournamentDetail.module.css";
import {
  createBracketQueryPlan,
  deriveBracketLoadState,
  isStageVisibleToViewer
} from "./bracketData";
import { buildLiveTeamStreams } from "./bracketLiveStreams";
import { buildBracketTabs, buildGroupStagePanels, selectBracketStages } from "./bracketStages.model";
import { EliminationStagePanel } from "./EliminationStagePanel";
import { FfaStagePanel } from "./FfaStagePanel";
import { GroupStagePanel } from "./GroupStagePanel";
import { useBracketActions, useBracketViewer } from "./useBracketActions";
// Re-exported purely so TournamentBracketPage.test.ts's dynamic-import probe
// (`bracketModule.getBracketRefetchInterval?.(status)`) can assert the
// lifecycle polling policy without reaching into bracketData.ts directly.
export { getBracketRefetchInterval } from "./bracketData";

function TournamentBracketView({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations();
  const searchParams = useSearchParams();
  const selectedStageParam = searchParams.get("stage");
  const viewParam = searchParams.get("view");
  // `?match=` deep link from the overview and matches sections: the bracket
  // scrolls that node into view and outlines it. Non-numeric → ignored.
  const matchParam = Number(searchParams.get("match"));
  const highlightMatchId = Number.isInteger(matchParam) && matchParam > 0 ? matchParam : null;

  const connectionState = useRealtimeStore((s) => s.connectionState);
  const viewer = useBracketViewer(tournament.workspace_id);

  const initialQueryPlan = useMemo(
    () => createBracketQueryPlan(tournament, selectedStageParam),
    [selectedStageParam, tournament]
  );
  const stagesQuery = useQuery(initialQueryPlan.stages);
  const queryPlan = useMemo(
    () => createBracketQueryPlan(tournament, selectedStageParam, stagesQuery.data),
    [selectedStageParam, stagesQuery.data, tournament]
  );
  const encountersQuery = useQuery(queryPlan.encounters);
  const standingsQuery = useQuery(queryPlan.standings);
  // A stage the organizer generated ahead of time (`is_published=false`) is a
  // preview: hidden from spectators entirely, visible to admins with a badge
  // and no report action (the backend rejects captain reports/veto for it
  // regardless — see `shared.services.bracket.usability.is_encounter_live`).
  const stages = (stagesQuery.data ?? []).filter((stage) =>
    isStageVisibleToViewer(stage, viewer.isAdmin)
  );
  const stageById = useMemo(() => new Map(stages.map((stage) => [stage.id, stage])), [stages]);

  // Read-only consumer of the stream cache the tournament shell already owns:
  // `TournamentClientLayout` is subscribed to `tournament:{id}:streams` and
  // invalidates `tournamentQueryKeys.streams(id)` on every event. A second
  // subscription here, or a second `useQuery` declaring the same key with its own
  // options, would be a rival updater of one cache entry — so this reuses the
  // shared hook and lets the layout stay the only writer.
  const streamsQuery = useTournamentStreamsQuery(tournament.id);
  const liveTeamStreams = useMemo(
    () => buildLiveTeamStreams(streamsQuery.data),
    [streamsQuery.data]
  );

  const actions = useBracketActions({
    tournament,
    viewer,
    stageById,
    encountersQueryKey: queryPlan.encounters.queryKey,
    refetchEncounters: () => void encountersQuery.refetch()
  });

  const selection = selectBracketStages(stages, viewParam, queryPlan.initialStageId);
  const { activeStages, activeGroupStages, groupStages, eliminationStages, shouldShowGroupStage } =
    selection;

  const stageIdsWithMatches = useMemo(
    () => new Set((encountersQuery.data?.results ?? []).map((encounter) => encounter.stage_id)),
    [encountersQuery.data?.results]
  );

  const bracketTabs = useMemo(
    () =>
      buildBracketTabs({
        tournament,
        groupStages,
        eliminationStages,
        activeStageId: queryPlan.initialStageId ?? selection.fallbackStage?.id,
        viewParam,
        matchCountsKnown: encountersQuery.data !== undefined,
        stageIdsWithMatches,
        labels: { groupStage: t("common.groupStage"), playoff: t("common.playoff") }
      }),
    [
      groupStages,
      eliminationStages,
      selection.fallbackStage?.id,
      queryPlan.initialStageId,
      encountersQuery.data,
      stageIdsWithMatches,
      viewParam,
      tournament,
      t
    ]
  );

  const allEncounters = encountersQuery.data;
  const allStandings = useMemo(() => standingsQuery.data ?? [], [standingsQuery.data]);

  const groupStagePanels = useMemo(
    () => buildGroupStagePanels(activeGroupStages, allEncounters?.results ?? [], allStandings),
    [activeGroupStages, allEncounters?.results, allStandings]
  );

  const encountersByStage = useMemo(() => {
    const map = new Map<number, Encounter[]>();
    for (const stage of activeStages) {
      map.set(
        stage.id,
        (allEncounters?.results ?? []).filter((encounter) => encounter.stage_id === stage.id)
      );
    }
    return map;
  }, [activeStages, allEncounters?.results]);

  const playoffStandings = useMemo(
    () =>
      allStandings.filter((standing) =>
        ["single_elimination", "double_elimination"].includes(standing.stage?.stage_type ?? "")
      ),
    [allStandings]
  );

  const retryQueries = () => {
    const requests: Array<Promise<unknown>> = [stagesQuery.refetch()];
    if (queryPlan.initialStageId != null) {
      requests.push(encountersQuery.refetch(), standingsQuery.refetch());
    }
    void Promise.all(requests);
  };
  const loadState = deriveBracketLoadState({
    hasStageId: queryPlan.initialStageId != null,
    stages: {
      hasData: stagesQuery.data !== undefined,
      isPending: stagesQuery.isPending,
      isError: stagesQuery.isError,
      isFetching: stagesQuery.isFetching
    },
    encounters: {
      hasData: encountersQuery.data !== undefined,
      isPending: encountersQuery.isPending,
      isError: encountersQuery.isError,
      isFetching: encountersQuery.isFetching
    },
    standings: {
      hasData: standingsQuery.data !== undefined,
      isPending: standingsQuery.isPending,
      isError: standingsQuery.isError,
      isFetching: standingsQuery.isFetching
    }
  });

  if (loadState.kind === "initial-error") {
    return <TournamentPageState state="initial-error" onRetry={retryQueries} />;
  }

  if (loadState.kind === "initial-loading") {
    return <TournamentBracketSkeleton />;
  }

  const content = (
    <>
      <ConnectionIndicator
        connectionState={connectionState}
        className="pointer-events-none fixed bottom-4 start-4 z-30"
      />
      <div className={styles.publicDataPage} data-page-section="bracket">
        {loadState.isUpdating && loadState.kind !== "refresh-error" ? <UpdatingBadge /> : null}
        {activeStages.length > 0 ? (
          <div className="space-y-6">
            {shouldShowGroupStage
              ? groupStagePanels.map((panel, index) =>
                  FFA_STAGE_TYPES.includes(panel.stage.stage_type) ? (
                    <FfaStagePanel
                      key={panel.key}
                      tournamentId={tournament.id}
                      stage={panel.stage}
                      bracketTabs={index === 0 ? bracketTabs : undefined}
                    />
                  ) : (
                    <GroupStagePanel
                      key={panel.key}
                      stage={panel.stage}
                      stageItem={panel.stageItem}
                      encounters={panel.encounters}
                      standings={panel.standings}
                      stages={stages}
                      onEdit={actions.handleEdit}
                      onReport={actions.handleReport}
                      canEdit={actions.canEdit}
                      canReport={actions.canReport}
                      onSwapSlots={actions.handleSwapSlots}
                      bracketTabs={index === 0 ? bracketTabs : undefined}
                      liveTeamStreams={liveTeamStreams}
                      defaultView={viewParam === "standings" ? "standings" : "matches"}
                      highlightMatchId={highlightMatchId}
                    />
                  )
                )
              : activeStages.map((stage) => {
                  const encounters = encountersByStage.get(stage.id) ?? [];
                  if (encounters.length === 0 && bracketTabs.length <= 1) {
                    return (
                      <div
                        key={stage.id}
                        className="rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-4 py-8 text-center text-[color:var(--aqt-fg-muted)]"
                      >
                        {t("common.noMatches", { stage: stage.name })}
                      </div>
                    );
                  }

                  const stagePlayoffStandings = playoffStandings.filter(
                    (standing) => standing.stage_id === stage.id
                  );

                  return (
                    <EliminationStagePanel
                      key={stage.id}
                      stage={stage}
                      encounters={encounters}
                      standings={stagePlayoffStandings}
                      stages={stages}
                      bracketTabs={bracketTabs}
                      defaultView={viewParam === "standings" ? "standings" : "bracket"}
                      crownTop={isTournamentStatusEnded(tournament.status)}
                      onEdit={actions.handleEdit}
                      onReport={actions.handleReport}
                      canEdit={actions.canEdit}
                      canReport={actions.canReport}
                      onSwapSlots={actions.handleSwapSlots}
                      liveTeamStreams={liveTeamStreams}
                      highlightMatchId={highlightMatchId}
                    />
                  );
                })}
          </div>
        ) : (
          <TournamentPageState state="empty" />
        )}

        {actions.editEncounter && (
          <EncounterEditDialog
            open={!!actions.editEncounter}
            onOpenChange={(open) => {
              if (!open) actions.setEditEncounter(null);
            }}
            encounter={actions.editEncounter}
          />
        )}

        {actions.reportEncounter && (
          <MatchReportDialog
            open={!!actions.reportEncounter}
            onOpenChange={(open) => {
              if (!open) actions.setReportEncounter(null);
            }}
            encounter={actions.reportEncounter}
          />
        )}
      </div>
    </>
  );

  if (loadState.kind === "refresh-error") {
    return (
      <TournamentPageState
        state="refresh-error"
        onRetry={retryQueries}
        isUpdating={loadState.isUpdating}
      >
        {content}
      </TournamentPageState>
    );
  }

  return content;
}

/**
 * Resolves the shared tournament overview so the route file stays a thin
 * server boundary, matching every other tournament sub-route. The overview is
 * hydrated by that boundary, so this is a cache read in practice — the guards
 * below only fire if that contract ever changes.
 */
export default function TournamentBracketPage({ slug }: Readonly<{ slug: string }>) {
  // Keyed by `slug`: shares TournamentClientLayout's overview cache entry.
  const tournamentQuery = useTournamentQuery(slug);

  if (!tournamentQuery.data) {
    if (tournamentQuery.isError) {
      return (
        <TournamentPageState state="initial-error" onRetry={() => void tournamentQuery.refetch()} />
      );
    }
    return <TournamentBracketSkeleton />;
  }

  return <TournamentBracketView tournament={tournamentQuery.data} />;
}
