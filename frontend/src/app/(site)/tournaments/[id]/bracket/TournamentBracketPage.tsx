"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { BracketView } from "@/components/BracketView";
import StandingsTable from "@/components/StandingsTable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EncounterEditDialog } from "@/components/tournaments/EncounterEditDialog";
import { MatchReportDialog } from "@/components/tournaments/MatchReportDialog";
import { useToast } from "@/hooks/use-toast";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import captainService from "@/services/captain.service";
import encounterService from "@/services/encounter.service";
import tournamentService from "@/services/tournament.service";
import type { Encounter } from "@/types/encounter.types";
import type { Standings, Tournament, Stage, StageItem } from "@/types/tournament.types";

import { useTranslation } from "@/i18n/LanguageContext";

const ADMIN_ROLES = new Set(["admin", "superadmin", "tournament_admin"]);
const BRACKET_REFRESH_INTERVAL_MS = 60_000;

interface TournamentBracketPageProps {
  tournament: Tournament;
  stages: Stage[];
}

function GroupStagePanel({
  stage,
  stageItem,
  encounters,
  standings,
  onEdit,
  onReport,
  canEdit,
  canReport,
}: {
  stage: Stage;
  stageItem?: StageItem;
  encounters: Encounter[];
  standings: Standings[];
  onEdit?: (encounter: Encounter) => void;
  onReport?: (encounter: Encounter) => void;
  canEdit?: (encounter: Encounter) => boolean;
  canReport?: (encounter: Encounter) => boolean;
}) {
  const { t } = useTranslation();
  const hasStandings = standings.length > 0;
  const title = stageItem?.name ?? stage.name;
  const subtitle = stageItem
    ? `${stage.name} - ${stage.stage_type.replace(/_/g, " ")}`
    : stage.stage_type.replace(/_/g, " ");

  return (
    <Tabs
      defaultValue={hasStandings ? "matches" : "matches"}
      className="overflow-hidden rounded-2xl border border-[var(--aqt-border)] bg-[var(--aqt-card)]"
    >
      <div className="flex flex-col gap-3 border-b border-[var(--aqt-border)] bg-[hsl(0_0%_100%/0.012)] px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h3 className="truncate text-lg font-semibold text-white">{title}</h3>
          <p className="mt-1 text-xs uppercase tracking-[0.18em] text-white/35">
            {subtitle}
          </p>
        </div>

        <TabsList className="h-auto justify-start rounded-xl border border-[var(--aqt-border)] bg-[hsl(0_0%_0%/0.25)] p-1 text-[var(--aqt-fg-muted)]">
          {hasStandings && (
            <TabsTrigger
              value="standings"
              className="rounded-lg px-4 py-2 text-sm data-[state=active]:bg-[hsl(174_72%_46%/0.14)] data-[state=active]:text-[var(--aqt-teal)] data-[state=active]:shadow-none"
            >
              {t("common.standings")}
            </TabsTrigger>
          )}
          <TabsTrigger
            value="matches"
            className="rounded-lg px-4 py-2 text-sm data-[state=active]:bg-[hsl(174_72%_46%/0.14)] data-[state=active]:text-[var(--aqt-teal)] data-[state=active]:shadow-none"
          >
            {t("common.bracket")}
          </TabsTrigger>
        </TabsList>
      </div>

      {hasStandings && (
        <TabsContent value="standings" className="mt-0">
          <div className="overflow-x-auto">
            <StandingsTable standings={[...standings]} is_groups={true} />
          </div>
        </TabsContent>
      )}

      <TabsContent value="matches" className="mt-0 p-4">
        <BracketView
          encounters={encounters}
          type={stage.stage_type}
          onEdit={onEdit}
          onReport={onReport}
          canEdit={canEdit}
          canReport={canReport}
        />
      </TabsContent>
    </Tabs>
  );
}


function getGroupScopeCount(stages: Stage[]) {
  return stages.reduce(
    (count, stage) => count + Math.max(stage.items.length, 1),
    0
  );
}

export default function TournamentBracketPage({
  tournament,
  stages,
}: TournamentBracketPageProps) {
  const searchParams = useSearchParams();
  const selectedStageParam = searchParams.get("stage");
  const viewParam = searchParams.get("view");

  const { status: authStatus, user: authUser } = useAuthProfile();
  const { toast } = useToast();
  const isAuthenticated = authStatus === "authenticated";
  const isAdmin =
    isAuthenticated &&
    (authUser?.isSuperuser ||
      (authUser?.roles ?? []).some((r) => ADMIN_ROLES.has(r)));

  const { t } = useTranslation();
  const [editEncounter, setEditEncounter] = useState<Encounter | null>(null);
  const [reportEncounter, setReportEncounter] = useState<Encounter | null>(null);

  const canEdit = isAdmin ? () => true : undefined;
  const canReport = isAuthenticated && !isAdmin
    ? (enc: Encounter) => enc.result_status !== "confirmed"
    : undefined;
  const handleEdit = isAdmin ? (enc: Encounter) => setEditEncounter(enc) : undefined;
  const handleReport = isAuthenticated && !isAdmin
    ? async (enc: Encounter) => {
        try {
          const { side } = await captainService.getMyRole(enc.id);
          if (side === null) {
            toast({ title: t("common.noAccess"), description: t("common.notCaptain"), variant: "destructive" });
            return;
          }
          setReportEncounter(enc);
        } catch {
          toast({ title: t("common.error"), description: t("common.roleVerificationFailed"), variant: "destructive" });
        }
      }
    : undefined;

  const groupStages = stages.filter(
    (stage) =>
      stage.stage_type === "round_robin" || stage.stage_type === "swiss"
  );

  const eliminationStages = stages.filter(
    (stage) =>
      stage.stage_type === "single_elimination" ||
      stage.stage_type === "double_elimination"
  );

  const fallbackStage = eliminationStages[0] ?? stages[0];
  const requestedStageId = selectedStageParam ? Number(selectedStageParam) : null;
  const requestedStage = stages.find((stage) => stage.id === requestedStageId);
  const primaryStage = requestedStage ?? fallbackStage;
  const requestedGroupStage =
    requestedStage && groupStages.some((stage) => stage.id === requestedStage.id)
      ? requestedStage
      : null;
  const shouldShowGroupStage =
    viewParam === "groups" ||
    requestedGroupStage != null;
  const activeGroupStages = shouldShowGroupStage
    ? viewParam === "groups"
      ? groupStages
      : requestedGroupStage
        ? [requestedGroupStage]
        : []
    : [];
  const activeStages = shouldShowGroupStage
    ? activeGroupStages
    : primaryStage
      ? [primaryStage]
      : [];

  const { data: allEncounters } = useQuery({
    queryKey: ["encounters", "tournament", tournament.id, tournament.workspace_id],
    queryFn: () =>
      encounterService.getAll(
        1,
        "",
        tournament.id,
        -1,
        undefined,
        undefined,
        tournament.workspace_id
      ),
    refetchInterval: BRACKET_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: true,
  });

  const { data: allStandings = [] } = useQuery({
    queryKey: ["standings", tournament.id, tournament.workspace_id],
    queryFn: () =>
      tournamentService.getStandings(tournament.id, tournament.workspace_id),
    refetchInterval: BRACKET_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: true,
  });

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
            standings: allStandings.filter(
              (standing) => standing.stage_id === stage.id
            ),
          },
        ];
      }

      return stage.items.map((stageItem) => ({
        key: `stage-${stage.id}-item-${stageItem.id}`,
        stage,
        stageItem,
        encounters: encounters.filter(
          (encounter) =>
            encounter.stage_id === stage.id &&
            encounter.stage_item_id === stageItem.id
        ),
        standings: allStandings.filter(
          (standing) =>
            standing.stage_id === stage.id &&
            standing.stage_item_id === stageItem.id
        ),
      }));
    });
  }, [activeGroupStages, allEncounters?.results, allStandings]);

  const encountersByStage = useMemo(() => {
    const map = new Map<number, Encounter[]>();

    for (const stage of activeStages) {
      map.set(
        stage.id,
        (allEncounters?.results ?? []).filter(
          (encounter) => encounter.stage_id === stage.id
        )
      );
    }

    return map;
  }, [activeStages, allEncounters?.results]);

  const playoffStandings = useMemo(
    () =>
      allStandings.filter((standing) =>
        ["single_elimination", "double_elimination"].includes(
          standing.stage?.stage_type ?? ""
        )
      ),
    [allStandings]
  );

  return (
    <div className="space-y-5">
      {activeStages.length > 0 ? (
        <div className="space-y-6">
          {shouldShowGroupStage
            ? groupStagePanels.map((panel) => (
                <GroupStagePanel
                  key={panel.key}
                  stage={panel.stage}
                  stageItem={panel.stageItem}
                  encounters={panel.encounters}
                  standings={panel.standings}
                  onEdit={handleEdit}
                  onReport={handleReport}
                  canEdit={canEdit}
                  canReport={canReport}
                />
              ))
            : activeStages.map((stage) => {
            const encounters = encountersByStage.get(stage.id) ?? [];
            if (encounters.length === 0) {
              return (
                <div
                  key={stage.id}
                  className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-8 text-center text-muted-foreground"
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
                defaultValue="bracket"
                className="overflow-hidden rounded-2xl border border-[var(--aqt-border)] bg-[var(--aqt-card)]"
              >
                <div className="flex flex-col gap-3 border-b border-[var(--aqt-border)] bg-[hsl(0_0%_100%/0.012)] px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <h3 className="truncate text-lg font-semibold text-white">{stage.name}</h3>
                    <p className="mt-1 text-xs uppercase tracking-[0.18em] text-white/35">
                      {stage.stage_type.replace(/_/g, " ")}
                    </p>
                  </div>

                  <TabsList className="h-auto justify-start rounded-xl border border-[var(--aqt-border)] bg-[hsl(0_0%_0%/0.25)] p-1 text-[var(--aqt-fg-muted)]">
                    {hasPlayoffStandings && (
                      <TabsTrigger
                        value="standings"
                        className="rounded-lg px-4 py-2 text-sm data-[state=active]:bg-[hsl(174_72%_46%/0.14)] data-[state=active]:text-[var(--aqt-teal)] data-[state=active]:shadow-none"
                      >
                        {t("common.standings")}
                      </TabsTrigger>
                    )}
                    <TabsTrigger
                      value="bracket"
                      className="rounded-lg px-4 py-2 text-sm data-[state=active]:bg-[hsl(174_72%_46%/0.14)] data-[state=active]:text-[var(--aqt-teal)] data-[state=active]:shadow-none"
                    >
                      {t("common.bracket")}
                    </TabsTrigger>
                  </TabsList>
                </div>

                {hasPlayoffStandings && (
                  <TabsContent value="standings" className="mt-0">
                    <div className="overflow-x-auto">
                      <StandingsTable standings={[...stagePlayoffStandings]} is_groups={false} />
                    </div>
                  </TabsContent>
                )}

                <TabsContent value="bracket" className="mt-0 p-4">
                  <BracketView
                    encounters={encounters}
                    type={stage.stage_type}
                    onEdit={handleEdit}
                    onReport={handleReport}
                    canEdit={canEdit}
                    canReport={canReport}
                  />
                </TabsContent>
              </Tabs>
            );
          })}
        </div>
      ) : (
        <div className="py-12 text-center text-muted-foreground">
          {stages.length === 0
            ? t("common.noStages")
            : t("common.noBracketMatches")}
        </div>
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
  );
}

