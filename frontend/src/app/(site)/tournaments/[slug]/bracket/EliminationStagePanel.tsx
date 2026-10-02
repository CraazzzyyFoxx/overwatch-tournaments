"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import StandingsTable from "@/components/StandingsTable";
import { BracketView, type BracketSlotRef } from "@/components/bracket/BracketView";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { previewToBracketMatches } from "@/lib/bracket/view";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { tournamentTeamsQueryOptions } from "@/lib/tournament/teams-query";
import tournamentService from "@/services/tournament.service";
import type { SegmentedLinkItem } from "@/components/ui/segmented";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import type { Encounter } from "@/types/encounter.types";
import type { StreamEntry } from "@/types/stream.types";
import type { Stage, Standings } from "@/types/tournament.types";

import { isStagePreview } from "./bracketData";
import { BracketScroller } from "./BracketScroller";
import { ResponsiveBracket } from "./ResponsiveBracket";
import { StagePanelHeader, ViewTabs } from "./StagePanelChrome";

type EliminationStagePanelProps = {
  stage: Stage;
  encounters: Encounter[];
  /** For the team names a projected bracket's seeded slots show. */
  workspaceId: number;
  /** This stage's playoff standings, already filtered by the caller. */
  standings: Standings[];
  stages: Stage[];
  bracketTabs: readonly SegmentedLinkItem[];
  /** `?view=standings` opens the table first; anything else opens the bracket. */
  defaultView: "bracket" | "standings";
  /** The champion gets a crown only once the tournament is over. */
  crownTop: boolean;
  onEdit?: (encounter: Encounter) => void;
  onReport?: (encounter: Encounter) => void;
  canEdit?: (encounter: Encounter) => boolean;
  canReport?: (encounter: Encounter) => boolean;
  onSwapSlots?: (
    source: BracketSlotRef<Encounter>,
    target: BracketSlotRef<Encounter>
  ) => Promise<unknown>;
  liveTeamStreams?: ReadonlyMap<number, StreamEntry>;
  highlightMatchId: number | null;
};

/**
 * A bracket with no matches yet, drawn as the generator would build it right
 * now — the same skeleton the organizer sees in the admin preview, look-only.
 * Its ids are skeleton-local, so nothing on it may link anywhere.
 */
function ProjectedBracket({ stage, workspaceId }: Readonly<{ stage: Stage; workspaceId: number }>) {
  const t = useTranslations();
  const previewQuery = useQuery({
    queryKey: tournamentQueryKeys.stageBracketPreview(stage.tournament_id, stage.id, stage),
    queryFn: () => tournamentService.getStageBracketPreview(stage.tournament_id, stage.id)
  });
  // Placeholder seeds are negative; only a seeded slot has a team to name.
  const hasTeams = (previewQuery.data ?? []).some(
    (row) => (row.home_team_id ?? 0) > 0 || (row.away_team_id ?? 0) > 0
  );
  const teamsQuery = useQuery({
    ...tournamentTeamsQueryOptions({ id: stage.tournament_id, workspace_id: workspaceId }),
    enabled: hasTeams
  });
  const matches = useMemo(
    () =>
      previewToBracketMatches(
        previewQuery.data ?? [],
        new Map((teamsQuery.data?.results ?? []).map((team) => [team.id, team]))
      ),
    [previewQuery.data, teamsQuery.data]
  );

  if (previewQuery.isPending) return <Skeleton className="h-64 w-full rounded-2xl" />;
  if (matches.length === 0) {
    return (
      <div className="py-8 text-center text-[color:var(--aqt-fg-muted)]">
        {t("common.noMatches", { stage: stage.name })}
      </div>
    );
  }
  return (
    <BracketScroller>
      <BracketView encounters={matches} type={stage.stage_type} interactive={false} />
    </BracketScroller>
  );
}

/** One elimination stage as its bracket, with its final table beside it. */
export function EliminationStagePanel({
  stage,
  encounters,
  workspaceId,
  standings,
  stages,
  bracketTabs,
  defaultView,
  crownTop,
  onEdit,
  onReport,
  canEdit,
  canReport,
  onSwapSlots,
  liveTeamStreams,
  highlightMatchId
}: Readonly<EliminationStagePanelProps>) {
  const t = useTranslations();
  const hasStandings = standings.length > 0;
  const isPreview = isStagePreview(stage);

  return (
    <Tabs
      defaultValue={defaultView === "standings" && hasStandings ? "standings" : "bracket"}
      className="overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]"
    >
      <StagePanelHeader
        bracketTabs={bracketTabs}
        title={stage.name}
        subtitle={stage.stage_type.replace(/_/g, " ")}
        isPreview={isPreview}
        railSuffix={isPreview && <Badge variant="outline">{t("common.bracketPreview")}</Badge>}
        viewTabs={<ViewTabs hasStandings={hasStandings} bracketValue="bracket" />}
      />

      {hasStandings && (
        <TabsContent value="standings" className="mt-0">
          <div className="min-w-0 overflow-x-auto">
            <StandingsTable
              standings={standings}
              stages={stages}
              is_groups={false}
              crownTop={crownTop}
            />
          </div>
        </TabsContent>
      )}

      <TabsContent value="bracket" className="mt-0 p-4">
        {encounters.length === 0 ? (
          stage.is_completed ? (
            <div className="py-8 text-center text-[color:var(--aqt-fg-muted)]">
              {t("common.noMatches", { stage: stage.name })}
            </div>
          ) : (
            <ProjectedBracket stage={stage} workspaceId={workspaceId} />
          )
        ) : (
          <BracketScroller>
            <ResponsiveBracket
              encounters={encounters}
              type={stage.stage_type}
              onEdit={onEdit}
              onReport={onReport}
              canEdit={canEdit}
              canReport={canReport}
              onSwapSlots={onSwapSlots}
              liveTeamStreams={liveTeamStreams}
              interactive={!isPreview}
              highlightMatchId={highlightMatchId}
            />
          </BracketScroller>
        )}
      </TabsContent>
    </Tabs>
  );
}
