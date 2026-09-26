"use client";

import { useTranslations } from "next-intl";

import StandingsTable from "@/components/StandingsTable";
import type { BracketSlotRef } from "@/components/bracket/BracketView";
import type { SegmentedLinkItem } from "@/components/ui/segmented";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import type { Encounter } from "@/types/encounter.types";
import type { StreamEntry } from "@/types/stream.types";
import type { Stage, Standings } from "@/types/tournament.types";

import { BracketScroller } from "./BracketScroller";
import { ResponsiveBracket } from "./ResponsiveBracket";
import { StagePanelHeader, ViewTabs } from "./StagePanelChrome";

type EliminationStagePanelProps = {
  stage: Stage;
  encounters: Encounter[];
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

/** One elimination stage as its bracket, with its final table beside it. */
export function EliminationStagePanel({
  stage,
  encounters,
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

  return (
    <Tabs
      defaultValue={defaultView === "standings" && hasStandings ? "standings" : "bracket"}
      className="overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]"
    >
      <StagePanelHeader
        bracketTabs={bracketTabs}
        title={stage.name}
        subtitle={stage.stage_type.replace(/_/g, " ")}
        isPreview={!stage.is_published && !stage.is_completed}
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
          <div className="py-8 text-center text-[color:var(--aqt-fg-muted)]">
            {t("common.noMatches", { stage: stage.name })}
          </div>
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
              highlightMatchId={highlightMatchId}
            />
          </BracketScroller>
        )}
      </TabsContent>
    </Tabs>
  );
}
