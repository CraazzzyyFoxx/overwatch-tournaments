"use client";

import React, { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import dynamic from "next/dynamic";
import { MatchWithStats } from "@/types/encounter.types";
import type { DivisionGridVersion } from "@/types/workspace.types";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  COLUMN_PRESETS,
  PRESET_ORDER,
  PresetKey,
  availableRounds,
  columnMaxima
} from "@/utils/matchStats";
import MatchTeamTable from "@/app/(site)/matches/[id]/components/MatchTeamTable";
import MatchTeamComparison from "@/app/(site)/matches/[id]/components/MatchTeamComparison";
import MatchLeaders from "@/app/(site)/matches/[id]/components/MatchLeaders";
import { Skeleton } from "@/components/ui/skeleton";
import MatchKillFeedTimeline from "@/app/(site)/matches/[id]/components/MatchKillFeedTimeline";

// recharts is ~100 kB of the client bundle and only the "comparison" tab ever
// renders it, so it loads on demand. The placeholder matches the chart's own
// minimum height (220px + the stat toggles) so the tab does not jump.
const MatchContributionChart = dynamic(
  () => import("@/app/(site)/matches/[id]/components/MatchContributionChart"),
  { ssr: false, loading: () => <Skeleton className="h-70 w-full rounded-lg" /> }
);

interface MatchStatsSectionProps {
  match: MatchWithStats;
  tournamentGrid?: DivisionGridVersion | null;
}

type ViewMode = "simple" | "extended";
type ExtendedTab = "tables" | "comparison" | "timeline";

const ControlLabel = ({ children }: { children: React.ReactNode }) => (
  <span className="aqt-tnum text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
    {children}
  </span>
);

const MatchStatsSection = ({ match, tournamentGrid }: MatchStatsSectionProps) => {
  const t = useTranslations<never>();
  const home = match.home_team;
  const away = match.away_team;

  const rounds = useMemo(() => availableRounds(home, away), [home, away]);
  const [mode, setMode] = useState<ViewMode>("simple");
  const [round, setRound] = useState<number>(0);
  const [preset, setPreset] = useState<PresetKey>("overview");
  const [tab, setTab] = useState<ExtendedTab>("tables");

  const activeRound = rounds.includes(round) ? round : 0;
  // Simple view is a fixed scoreboard (overview columns); extended follows the preset.
  const columns = mode === "simple" ? COLUMN_PRESETS.overview : COLUMN_PRESETS[preset];
  const columnMax = useMemo(
    () => columnMaxima(home, away, activeRound, columns),
    [home, away, activeRound, columns]
  );

  const roundLabel = (value: number) =>
    value === 0 ? t("matches.allMatch") : t("matches.round", { round: value });

  // Round is relevant everywhere except the timeline (which spans the whole match).
  const showRound = rounds.length > 1 && (mode === "simple" || tab !== "timeline");
  const roundControl = showRound ? (
    <div className="flex items-center gap-2">
      <ControlLabel>{t("matches.roundLabel")}</ControlLabel>
      <Select value={String(activeRound)} onValueChange={(value) => setRound(Number(value))}>
        <SelectTrigger className="h-8 w-[150px] text-caption">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {rounds.map((value) => (
            <SelectItem key={value} value={String(value)}>
              {roundLabel(value)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  ) : null;

  // ONE table, ONE horizontal scroll container, two `<tbody>` sections. Two
  // sibling tables each scrolled independently, so reaching a right-hand stat
  // column on one team desynced it from the other — the exact comparison this
  // panel exists to make.
  const tables = (
    <div className="overflow-hidden rounded-[12px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]">
      <div className="relative w-full overflow-auto">
        <table className="w-full caption-bottom text-sm">
          <MatchTeamTable
            team={home}
            isHome={true}
            matchRound={activeRound}
            columns={columns}
            columnMax={columnMax}
            tournamentGrid={tournamentGrid}
          />
          <MatchTeamTable
            team={away}
            isHome={false}
            matchRound={activeRound}
            columns={columns}
            columnMax={columnMax}
            tournamentGrid={tournamentGrid}
          />
        </table>
      </div>
    </div>
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Single control bar: view mode + (contextual) round */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ToggleGroup
          type="single"
          value={mode}
          onValueChange={(value) => value && setMode(value as ViewMode)}
          variant="pill"
          size="sm"
        >
          <ToggleGroupItem value="simple">{t("matches.view.simple")}</ToggleGroupItem>
          <ToggleGroupItem value="extended">{t("matches.view.extended")}</ToggleGroupItem>
        </ToggleGroup>
        {roundControl}
      </div>

      {mode === "simple" ? (
        tables
      ) : (
        <Tabs value={tab} onValueChange={(value) => setTab(value as ExtendedTab)}>
          <TabsList>
            <TabsTrigger value="tables">{t("matches.tab.tables")}</TabsTrigger>
            <TabsTrigger value="comparison">{t("matches.tab.comparison")}</TabsTrigger>
            <TabsTrigger value="timeline">{t("matches.tab.timeline")}</TabsTrigger>
          </TabsList>

          <TabsContent value="tables" className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <ControlLabel>{t("matches.tableView")}</ControlLabel>
              <Select value={preset} onValueChange={(value) => setPreset(value as PresetKey)}>
                <SelectTrigger className="h-8 w-[160px] text-caption">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PRESET_ORDER.map((key) => (
                    <SelectItem key={key} value={key}>
                      {t(`matches.preset.${key}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {tables}
          </TabsContent>

          <TabsContent value="comparison" className="flex flex-col gap-5">
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
              <MatchTeamComparison home={home} away={away} round={activeRound} />
              <MatchContributionChart home={home} away={away} round={activeRound} />
            </div>
            <MatchLeaders home={home} away={away} round={activeRound} />
          </TabsContent>

          <TabsContent value="timeline">
            <MatchKillFeedTimeline matchId={match.id} home={home} away={away} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
};

export default MatchStatsSection;
