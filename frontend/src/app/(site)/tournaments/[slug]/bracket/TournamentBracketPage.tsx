"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { ResponsiveBracket } from "./ResponsiveBracket";
import { ConnectionIndicator } from "@/components/realtime/ConnectionIndicator";
import StandingsTable from "@/components/StandingsTable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { SegmentedLinks, type SegmentedLinkItem } from "@/components/ui/segmented";
import { toggleVariants, segmentedFrame } from "@/components/ui/toggle";
import { EncounterEditDialog } from "@/components/tournaments/EncounterEditDialog";
import { MatchReportDialog } from "@/components/tournaments/MatchReportDialog";
import { refreshEncounterViews } from "@/components/tournaments/refreshEncounterViews";
import type { BracketSlotRef } from "@/components/bracket/BracketView";
import { notify } from "@/lib/notify";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { usePermissions } from "@/hooks/usePermissions";
import { useRealtimeStore } from "@/stores/realtime.store";
import adminService from "@/services/admin.service";
import captainService from "@/services/captain.service";
import encounterService from "@/services/encounter.service";
import type { Encounter } from "@/types/encounter.types";
import type { PaginatedResponse } from "@/types/pagination.types";
import type { StreamEntry } from "@/types/stream.types";
import type { Standings, Tournament, Stage, StageItem } from "@/types/tournament.types";

import { ListOrdered, Network } from "lucide-react";
import { cn } from "@/lib/utils";
import { tournamentHref } from "@/lib/tournament-url";
import { useTranslations } from "next-intl";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentBracketSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { useTournamentStreamsQuery } from "../_hooks/useTournamentStreams";
import styles from "../TournamentDetail.module.css";
import { isTournamentStatusEnded } from "@/lib/tournament-status";
import {
  createBracketQueryPlan,
  deriveBracketLoadState,
  isStageReportable,
  isStageVisibleToViewer,
  swapSlotTeams
} from "./bracketData";
import { buildLiveTeamStreams } from "./bracketLiveStreams";
// Re-exported purely so TournamentBracketPage.test.ts's dynamic-import probe
// (`bracketModule.getBracketRefetchInterval?.(status)`) can assert the
// lifecycle polling policy without reaching into bracketData.ts directly.
export { getBracketRefetchInterval } from "./bracketData";

const ADMIN_ROLES = new Set(["admin", "superadmin", "tournament_admin"]);

/**
 * Standings ⇄ bracket switch, icon-only like the tournaments list's view
 * switch. Both bracket panels draw it, so the frame and the pill live in one
 * place instead of four copies of a 200-character class string.
 */
function ViewTabs({
  hasStandings,
  bracketValue
}: Readonly<{ hasStandings: boolean; bracketValue: string }>) {
  const t = useTranslations();
  const item = toggleVariants({ variant: "pill", size: "sm" });

  return (
    <TabsList className={cn(segmentedFrame, "h-8 text-[color:var(--aqt-fg-muted)]")}>
      {hasStandings && (
        <TabsTrigger value="standings" className={item}>
          <ListOrdered aria-hidden width={14} height={14} />
          <span className="sr-only">{t("common.standings")}</span>
        </TabsTrigger>
      )}
      <TabsTrigger value={bracketValue} className={item}>
        <Network aria-hidden width={14} height={14} />
        <span className="sr-only">{t("common.bracket")}</span>
      </TabsTrigger>
    </TabsList>
  );
}

interface TournamentBracketViewProps {
  tournament: Tournament;
}

function GroupStagePanel({
  stage,
  stageItem,
  encounters,
  standings,
  stages,
  onEdit,
  onReport,
  canEdit,
  canReport,
  onSwapSlots,
  bracketTabs,
  liveTeamStreams,
  defaultView = "matches",
  highlightMatchId = null
}: Readonly<{
  stage: Stage;
  stageItem?: StageItem;
  encounters: Encounter[];
  standings: Standings[];
  stages: Stage[];
  onEdit?: (encounter: Encounter) => void;
  onReport?: (encounter: Encounter) => void;
  canEdit?: (encounter: Encounter) => boolean;
  canReport?: (encounter: Encounter) => boolean;
  onSwapSlots?: (source: BracketSlotRef<Encounter>, target: BracketSlotRef<Encounter>) => Promise<unknown>;
  bracketTabs?: readonly SegmentedLinkItem[];
  liveTeamStreams?: ReadonlyMap<number, StreamEntry>;
  /** `?view=standings` opens the table first; anything else opens the matches. */
  defaultView?: "matches" | "standings";
  highlightMatchId?: number | null;
}>) {
  const t = useTranslations();
  const hasStandings = standings.length > 0;
  const isPreview = !stage.is_published && !stage.is_completed;
  const title = stageItem?.name ?? stage.name;
  const subtitle = stageItem
    ? `${stage.name} - ${stage.stage_type.replace(/_/g, " ")}`
    : stage.stage_type.replace(/_/g, " ");

  return (
    <Tabs
      defaultValue={defaultView === "standings" && hasStandings ? "standings" : "matches"}
      className="overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]"
    >
      <div className="flex flex-col gap-3 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
        {bracketTabs && bracketTabs.length > 1 ? (
          <div className="flex min-w-0 flex-col items-start gap-2">
            <div className="flex flex-wrap items-center gap-3">
              <SegmentedLinks
                items={bracketTabs}
                label={t("tournamentDetail.stageTabsLabel")}
                size="default"
              />
              {stageItem && (
                <span className="text-sm font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                  / {stageItem.name}
                </span>
              )}
              {isPreview && <Badge variant="outline">{t("common.bracketPreview")}</Badge>}
            </div>
            <p className="text-xs uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
              {subtitle}
            </p>
          </div>
        ) : (
          <div className="min-w-0">
            <h3 className="truncate text-lg font-semibold text-[color:var(--aqt-fg)]">
              {title}
              {isPreview && (
                <Badge variant="outline" className="ml-2 align-middle">
                  {t("common.bracketPreview")}
                </Badge>
              )}
            </h3>
            <p className="mt-1 text-xs uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
              {subtitle}
            </p>
          </div>
        )}

        <ViewTabs hasStandings={hasStandings} bracketValue="matches" />
      </div>

      {hasStandings && (
        <TabsContent value="standings" className="mt-0">
          <div className="min-w-0 overflow-x-auto">
            <StandingsTable standings={standings} stages={stages} is_groups />
          </div>
        </TabsContent>
      )}

      <TabsContent value="matches" className="mt-0 p-4">
        <section
          aria-label={t("tournamentDetail.bracketRegion")}
          tabIndex={0}
          className={styles.bracketScroller}
        >
          <ResponsiveBracket
            encounters={encounters}
            type={stage.stage_type}
            onEdit={onEdit}
            onReport={onReport}
            canEdit={canEdit}
            canReport={canReport}
            onSwapSlots={onSwapSlots}
            liveTeamStreams={liveTeamStreams}
            highlightMatchId={highlightMatchId}
          />
        </section>
      </TabsContent>
    </Tabs>
  );
}

function TournamentBracketView({ tournament }: Readonly<TournamentBracketViewProps>) {
  const searchParams = useSearchParams();
  const selectedStageParam = searchParams.get("stage");
  const viewParam = searchParams.get("view");
  // `?match=` deep link from the overview and matches sections: the bracket
  // scrolls that node into view and outlines it. Non-numeric → ignored.
  const matchParam = Number(searchParams.get("match"));
  const highlightMatchId = Number.isInteger(matchParam) && matchParam > 0 ? matchParam : null;

  const { isSuperuser, isWorkspaceAdmin } = usePermissions();
  const { status: authStatus, user: authUser } = useAuthProfile();
  const isAuthenticated = authStatus === "authenticated";
  const isAdmin =
    isAuthenticated &&
    (isSuperuser ||
      isWorkspaceAdmin(tournament.workspace_id) ||
      (authUser?.roles ?? []).some((r) => ADMIN_ROLES.has(r)));

  const t = useTranslations();
  const connectionState = useRealtimeStore((s) => s.connectionState);
  const [editEncounter, setEditEncounter] = useState<Encounter | null>(null);
  const [reportEncounter, setReportEncounter] = useState<Encounter | null>(null);

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
  const stages = (stagesQuery.data ?? []).filter((stage) => isStageVisibleToViewer(stage, isAdmin));
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

  const captainPlayerIds = useMemo(
    () => new Set((authUser?.linkedPlayers ?? []).map((p) => p.playerId)),
    [authUser?.linkedPlayers]
  );
  const isEncounterCaptain = (enc: Encounter) => {
    const homeCaptain = enc.home_team?.captain_id;
    const awayCaptain = enc.away_team?.captain_id;
    return (
      (homeCaptain != null && captainPlayerIds.has(homeCaptain)) ||
      (awayCaptain != null && captainPlayerIds.has(awayCaptain))
    );
  };
  const canEdit = isAdmin ? () => true : undefined;
  const canReport = isAuthenticated
    ? (enc: Encounter) =>
        enc.result_status !== "confirmed" &&
        isEncounterCaptain(enc) &&
        isStageReportable(enc.stage_id == null ? undefined : stageById.get(enc.stage_id))
    : undefined;
  const handleEdit = isAdmin ? (enc: Encounter) => setEditEncounter(enc) : undefined;
  const handleReport = isAuthenticated
    ? async (enc: Encounter) => {
        try {
          const [fresh, role] = await Promise.all([
            encounterService.getEncounter(enc.id),
            captainService.getMyRole(enc.id)
          ]);
          if (fresh.result_status === "confirmed") {
            // The result was confirmed after this bracket data was cached; the
            // report action is no longer valid. Tell the captain why, then
            // refresh so the stale report action disappears.
            notify.error(t("matchReport.confirmedLockedTitle"), {
              description: t("matchReport.confirmedLockedBody")
            });
            void encountersQuery.refetch();
            return;
          }
          if (role.side === null) {
            notify.error(t("common.noAccess"), { description: t("common.notCaptain") });
            return;
          }
          setReportEncounter(fresh);
        } catch {
          notify.error(t("common.error"), { description: t("common.roleVerificationFailed") });
        }
      }
    : undefined;
  // Rearrange mode (admins): one server call swaps two slots; the cache takes
  // the swap first so the dropped team stays put, and is restored if the server
  // refuses (a match went live between poll and drop).
  const queryClient = useQueryClient();
  const handleSwapSlots = isAdmin
    ? async (source: BracketSlotRef<Encounter>, target: BracketSlotRef<Encounter>) => {
        const key = queryPlan.encounters.queryKey;
        const previous = queryClient.getQueryData<PaginatedResponse<Encounter>>(key);
        if (previous) {
          queryClient.setQueryData<PaginatedResponse<Encounter>>(key, {
            ...previous,
            results: swapSlotTeams(
              previous.results,
              { encounterId: source.encounter.id, slot: source.slot },
              { encounterId: target.encounter.id, slot: target.slot }
            )
          });
        }
        try {
          await adminService.swapEncounterSlot(source.encounter.id, {
            slot: source.slot,
            target_encounter_id: target.encounter.id,
            target_slot: target.slot
          });
          notify.success(t("bracket.rearrangeDone"));
        } catch (error) {
          if (previous) queryClient.setQueryData(key, previous);
          notify.apiError(error, { title: t("bracket.rearrangeFailed") });
        }
        await refreshEncounterViews(queryClient, tournament.id);
      }
    : undefined;

  const groupStages = stages.filter(
    (stage) => stage.stage_type === "round_robin" || stage.stage_type === "swiss"
  );

  const eliminationStages = stages.filter(
    (stage) =>
      stage.stage_type === "single_elimination" || stage.stage_type === "double_elimination"
  );

  const activeStage = stages.find((stage) => stage.is_active);
  const fallbackStage = activeStage ?? eliminationStages[0] ?? stages[0];
  const requestedStage = stages.find((stage) => stage.id === queryPlan.initialStageId);
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
  const activeStages = shouldShowGroupStage
    ? activeGroupStages
    : primaryStage
      ? [primaryStage]
      : [];

  // The encounters query pulls the whole tournament, not just the selected
  // stage, so it also answers "does that other tab lead anywhere?". Until it
  // resolves nothing is disabled — a tab that flickers inert is worse than a
  // tab that lands on an empty state.
  const stageIdsWithMatches = useMemo(
    () => new Set((encountersQuery.data?.results ?? []).map((encounter) => encounter.stage_id)),
    [encountersQuery.data?.results]
  );
  const matchCountsKnown = encountersQuery.data !== undefined;

  const bracketTabs = useMemo(() => {
    const tabs: SegmentedLinkItem[] = [];

    const groupScopeCount = groupStages.reduce(
      (count, stage) => count + Math.max(stage.items.length, 1),
      0
    );

    const activeStageId = queryPlan.initialStageId ?? fallbackStage?.id;

    const isGroupViewActive =
      viewParam === "groups" ||
      (!!activeStageId && groupStages.some((stage) => stage.id === activeStageId));

    // The tab you are standing on stays live even when empty; you are already
    // looking at its empty state.
    const isDead = (isActive: boolean, stageIds: readonly number[]) =>
      !isActive && matchCountsKnown && !stageIds.some((id) => stageIdsWithMatches.has(id));

    if (groupScopeCount > 1) {
      tabs.push({
        key: "group-stage",
        href:
          groupStages.length === 1
            ? tournamentHref(tournament, `/bracket?stage=${groupStages[0].id}`)
            : tournamentHref(tournament, "/bracket?view=groups"),
        label: t("common.groupStage"),
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

    eliminationStages.forEach((stage) => {
      const isActive = !viewParam && stage.id === activeStageId;
      tabs.push({
        key: `stage-${stage.id}`,
        href: tournamentHref(tournament, `/bracket?stage=${stage.id}`),
        label:
          eliminationStages.length === 1 && groupStages.length > 0
            ? t("common.playoff")
            : stage.name,
        isActive,
        disabled: isDead(isActive, [stage.id])
      });
    });

    return tabs;
  }, [
    groupStages,
    eliminationStages,
    fallbackStage?.id,
    queryPlan.initialStageId,
    matchCountsKnown,
    stageIdsWithMatches,
    viewParam,
    tournament,
    t
  ]);

  const allEncounters = encountersQuery.data;
  const allStandings = standingsQuery.data ?? [];

  const groupStagePanels = useMemo(() => {
    const encounters = allEncounters?.results ?? [];

    return activeGroupStages.flatMap((stage) => {
      if (stage.items.length === 0) {
        return [
          {
            key: `stage-${stage.id}`,
            stage,
            stageItem: undefined as StageItem | undefined,
            encounters: encounters.filter((encounter) => encounter.stage_id === stage.id),
            standings: allStandings.filter((standing) => standing.stage_id === stage.id)
          }
        ];
      }

      return stage.items.map((stageItem) => ({
        key: `stage-${stage.id}-item-${stageItem.id}`,
        stage,
        stageItem,
        encounters: encounters.filter(
          (encounter) => encounter.stage_id === stage.id && encounter.stage_item_id === stageItem.id
        ),
        standings: allStandings.filter(
          (standing) => standing.stage_id === stage.id && standing.stage_item_id === stageItem.id
        )
      }));
    });
  }, [activeGroupStages, allEncounters?.results, allStandings]);

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
              ? groupStagePanels.map((panel, index) => (
                  <GroupStagePanel
                    key={panel.key}
                    stage={panel.stage}
                    stageItem={panel.stageItem}
                    encounters={panel.encounters}
                    standings={panel.standings}
                    stages={stages}
                    onEdit={handleEdit}
                    onReport={handleReport}
                    canEdit={canEdit}
                    canReport={canReport}
                    onSwapSlots={handleSwapSlots}
                    bracketTabs={index === 0 ? bracketTabs : undefined}
                    liveTeamStreams={liveTeamStreams}
                    defaultView={viewParam === "standings" ? "standings" : "matches"}
                    highlightMatchId={highlightMatchId}
                  />
                ))
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
                  const hasPlayoffStandings = stagePlayoffStandings.length > 0;

                  return (
                    <Tabs
                      key={stage.id}
                      defaultValue={
                        viewParam === "standings" && hasPlayoffStandings ? "standings" : "bracket"
                      }
                      className="overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]"
                    >
                      <div className="flex flex-col gap-3 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
                        {bracketTabs.length > 1 ? (
                          <div className="flex min-w-0 flex-col items-start gap-2">
                            <SegmentedLinks
                              items={bracketTabs}
                              label={t("tournamentDetail.stageTabsLabel")}
                              size="default"
                            />
                            <p className="text-xs uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                              {stage.stage_type.replace(/_/g, " ")}
                            </p>
                          </div>
                        ) : (
                          <div className="min-w-0">
                            <h3 className="truncate text-lg font-semibold text-[color:var(--aqt-fg)]">
                              {stage.name}
                              {!stage.is_published && !stage.is_completed && (
                                <Badge variant="outline" className="ml-2 align-middle">
                                  {t("common.bracketPreview")}
                                </Badge>
                              )}
                            </h3>
                            <p className="mt-1 text-xs uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                              {stage.stage_type.replace(/_/g, " ")}
                            </p>
                          </div>
                        )}

                        <ViewTabs hasStandings={hasPlayoffStandings} bracketValue="bracket" />
                      </div>

                      {hasPlayoffStandings && (
                        <TabsContent value="standings" className="mt-0">
                          <div className="min-w-0 overflow-x-auto">
                            <StandingsTable
                              standings={stagePlayoffStandings}
                              stages={stages}
                              is_groups={false}
                              crownTop={isTournamentStatusEnded(tournament.status)}
                            />
                          </div>
                        </TabsContent>
                      )}

                      <TabsContent value="bracket" className="mt-0 p-4">
                        {encounters.length === 0 ? (
                          <div className="py-8 text-center text-[color:var(--aqt-fg-muted)]">
                            {t("common.noMatches", { stage: stage.name })}
                          </div>
                        ) : (
                          <section
                            aria-label={t("tournamentDetail.bracketRegion")}
                            tabIndex={0}
                            className={styles.bracketScroller}
                          >
                            <ResponsiveBracket
                              encounters={encounters}
                              type={stage.stage_type}
                              onEdit={handleEdit}
                              onReport={handleReport}
                              canEdit={canEdit}
                              canReport={canReport}
                              onSwapSlots={handleSwapSlots}
                              liveTeamStreams={liveTeamStreams}
                              highlightMatchId={highlightMatchId}
                            />
                          </section>
                        )}
                      </TabsContent>
                    </Tabs>
                  );
                })}
          </div>
        ) : (
          <TournamentPageState state="empty" />
        )}

        {editEncounter && (
          <EncounterEditDialog
            open={!!editEncounter}
            onOpenChange={(open) => {
              if (!open) setEditEncounter(null);
            }}
            encounter={editEncounter}
          />
        )}

        {reportEncounter && (
          <MatchReportDialog
            open={!!reportEncounter}
            onOpenChange={(open) => {
              if (!open) setReportEncounter(null);
            }}
            encounter={reportEncounter}
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
 * Resolves the shared tournament overview so the route file stays a one-line
 * delegation, matching every other tournament sub-route. The overview is
 * already primed by the layout, so this is a cache read in practice — the
 * guards below only fire if that layout contract ever changes.
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
