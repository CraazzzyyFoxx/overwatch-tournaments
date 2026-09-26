"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import type { SegmentedLinkItem } from "@/components/ui/segmented";
import StandingsTable from "@/components/StandingsTable";
import type { BracketSlotRef } from "@/components/bracket/BracketView";
import type { Encounter } from "@/types/encounter.types";
import type { StreamEntry } from "@/types/stream.types";
import type { Stage, StageItem, Standings } from "@/types/tournament.types";

import { BracketScroller } from "./BracketScroller";
import { ResponsiveBracket } from "./ResponsiveBracket";
import { StagePanelHeader, ViewTabs } from "./StagePanelChrome";

type GroupStagePanelProps = {
  stage: Stage;
  stageItem?: StageItem;
  encounters: Encounter[];
  standings: Standings[];
  stages: Stage[];
  onEdit?: (encounter: Encounter) => void;
  onReport?: (encounter: Encounter) => void;
  canEdit?: (encounter: Encounter) => boolean;
  canReport?: (encounter: Encounter) => boolean;
  onSwapSlots?: (
    source: BracketSlotRef<Encounter>,
    target: BracketSlotRef<Encounter>
  ) => Promise<unknown>;
  bracketTabs?: readonly SegmentedLinkItem[];
  liveTeamStreams?: ReadonlyMap<number, StreamEntry>;
  /** `?view=standings` opens the table first; anything else opens the matches. */
  defaultView?: "matches" | "standings";
  highlightMatchId?: number | null;
};

/** One group (or one whole group stage) as its standings table and its matches. */
export function GroupStagePanel({
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
}: Readonly<GroupStagePanelProps>) {
  const t = useTranslations();
  const hasStandings = standings.length > 0;
  const isPreview = !stage.is_published && !stage.is_completed;

  return (
    <Tabs
      defaultValue={defaultView === "standings" && hasStandings ? "standings" : "matches"}
      className="overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]"
    >
      <StagePanelHeader
        bracketTabs={bracketTabs}
        title={stageItem?.name ?? stage.name}
        subtitle={
          stageItem
            ? `${stage.name} - ${stage.stage_type.replace(/_/g, " ")}`
            : stage.stage_type.replace(/_/g, " ")
        }
        isPreview={isPreview}
        railSuffix={
          <>
            {stageItem && (
              <span className="text-sm font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                / {stageItem.name}
              </span>
            )}
            {isPreview && <Badge variant="outline">{t("common.bracketPreview")}</Badge>}
          </>
        }
        viewTabs={<ViewTabs hasStandings={hasStandings} bracketValue="matches" />}
      />

      {hasStandings && (
        <TabsContent value="standings" className="mt-0">
          <div className="min-w-0 overflow-x-auto">
            <StandingsTable standings={standings} stages={stages} is_groups />
          </div>
        </TabsContent>
      )}

      <TabsContent value="matches" className="mt-0 p-4">
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
      </TabsContent>
    </Tabs>
  );
}
