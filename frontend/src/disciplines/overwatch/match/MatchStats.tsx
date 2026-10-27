"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import dynamic from "next/dynamic";
import type { SlotProps } from "@/disciplines/types";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { TooltipProvider } from "@/components/ui/tooltip";
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
} from "./stats";
import { owMatchView, type OwTeam } from "./view";
import TeamTable from "./TeamTable";
import TeamComparison from "./TeamComparison";
import Leaders from "./Leaders";
import { Skeleton } from "@/components/ui/skeleton";
import KillFeedTimeline from "./KillFeedTimeline";
import type { MatchWithStats } from "@/types/encounter.types";

// recharts is ~100 kB of the client bundle and only the "comparison" tab ever
// renders it, so it loads on demand. The placeholder matches the chart's own
// minimum height (220px + the stat toggles) so the tab does not jump.
const ContributionChart = dynamic(
  () => import("./ContributionChart"),
  { ssr: false, loading: () => <Skeleton className="h-70 w-full rounded-lg" /> }
);

interface MatchStatsViewProps {
  match: MatchWithStats;
  home: OwTeam;
  away: OwTeam;
}

type ViewMode = "simple" | "extended";
type ExtendedTab = "tables" | "comparison" | "timeline";

const MatchStatsView = ({ match, home, away }: MatchStatsViewProps) => {
  const t = useTranslations<never>();

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
      <Eyebrow className="aqt-tnum">{t("matches.roundLabel")}</Eyebrow>
      <Select value={String(activeRound)} onValueChange={(value) => setRound(Number(value))}>
        <SelectTrigger size="sm" className="w-[150px]">
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
    <Card className="overflow-hidden">
      <div className="relative w-full overflow-auto">
        {/* The rating column's MVP cards: one provider, so moving between badges skips the open delay. */}
        <TooltipProvider>
          <table className="w-full caption-bottom text-sm">
            <TeamTable
              team={home}
              isHome={true}
              matchRound={activeRound}
              columns={columns}
              columnMax={columnMax}
            />
            <TeamTable
              team={away}
              isHome={false}
              matchRound={activeRound}
              columns={columns}
              columnMax={columnMax}
            />
          </table>
        </TooltipProvider>
      </div>
    </Card>
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Single control bar: view mode + (contextual) round */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ToggleGroup
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
              <Eyebrow className="aqt-tnum">{t("matches.tableView")}</Eyebrow>
              <Select value={preset} onValueChange={(value) => setPreset(value as PresetKey)}>
                <SelectTrigger size="sm" className="w-[160px]">
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
              <TeamComparison home={home} away={away} round={activeRound} />
              <ContributionChart home={home} away={away} round={activeRound} />
            </div>
            <Leaders home={home} away={away} round={activeRound} />
          </TabsContent>

          <TabsContent value="timeline">
            <KillFeedTimeline matchId={match.id} members={match.statistics.members} home={home} away={away} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
};

/**
 * The Overwatch scoreboard of a duel: summary and extended tables, team comparison, contribution chart, leaders
 * and the kill timeline. The host renders it only for a match with exactly two participants.
 */
export default function MatchStats({ match }: Readonly<SlotProps["matchStats"]>) {
  const view = useMemo(() => owMatchView(match), [match]);
  if (!view) return null;
  return <MatchStatsView match={match} home={view.home} away={view.away} />;
}
