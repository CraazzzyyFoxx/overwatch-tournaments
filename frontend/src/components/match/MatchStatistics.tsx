"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import LabelledSelect from "@/components/match/LabelledSelect";
import MatchEventsTimeline from "@/components/match/MatchEventsTimeline";
import { useSegmentLabel } from "@/components/match/segment-label";
import StatsTableView from "@/components/match/StatsTable";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DisciplineWidget } from "@/disciplines/DisciplineWidget";
import { loadMatchUI } from "@/disciplines/registry/match";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { buildMatchTable, hasMemberFacts, matchSegments, memberEntities } from "@/lib/stats/table";
import type { DisciplineMetadata } from "@/types/discipline.types";
import type { MatchWithStats } from "@/types/encounter.types";

const TOTALS = "none";

/**
 * The working generic view of a native match: every participation (any number) with its observed members, one
 * declared stat per column, for a selected segment and grain (the member totals, or one character's rows —
 * never both added), plus the match's native event timeline. Used where no module renderer applies (another
 * game, or a match that is not a duel) and while a module's renderer loads.
 */
function GenericMatchStatistics({
  match,
  metadata
}: Readonly<{ match: MatchWithStats; metadata: DisciplineMetadata }>) {
  const t = useTranslations();
  const segments = matchSegments(match);
  const segmentLabel = useSegmentLabel(match.statistics.segments);
  const [tab, setTab] = useState<"statistics" | "timeline">("statistics");
  const [segment, setSegment] = useState(0);
  const [entity, setEntity] = useState<string>(TOTALS);

  const activeSegment = segments.includes(segment) ? segment : 0;
  const entities = useMemo(() => memberEntities([match], activeSegment), [match, activeSegment]);
  const activeEntity = entities.some((candidate) => String(candidate.id) === entity)
    ? Number(entity)
    : TOTALS;
  const table = useMemo(
    () =>
      buildMatchTable(match, metadata.stat_defs, { segment: activeSegment, entity: activeEntity }),
    [match, metadata.stat_defs, activeSegment, activeEntity]
  );

  return (
    <Tabs value={tab} onValueChange={(value) => setTab(value as typeof tab)}>
      <TabsList>
        <TabsTrigger value="statistics">{t("matches.native.statistics")}</TabsTrigger>
        <TabsTrigger value="timeline">{t("matches.tab.timeline")}</TabsTrigger>
      </TabsList>

      <TabsContent value="statistics" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {segments.length > 1 ? (
            <LabelledSelect
              label={t("matches.native.segmentLabel")}
              value={String(activeSegment)}
              onValueChange={(value) => setSegment(Number(value))}
              options={segments.map((value) => ({
                value: String(value),
                label: segmentLabel(value)
              }))}
            />
          ) : null}
          {entities.length > 0 ? (
            <LabelledSelect
              label={t("matches.native.grainLabel")}
              value={String(activeEntity)}
              onValueChange={setEntity}
              options={[
                { value: TOTALS, label: t("matches.native.grainTotals") },
                ...entities.map((candidate) => ({
                  value: String(candidate.id),
                  label: candidate.name
                }))
              ]}
            />
          ) : null}
        </div>
        {!hasMemberFacts(match) ? (
          <p className="text-sm text-muted-foreground">{t("matches.native.noStats")}</p>
        ) : table.columns.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("matches.native.noValues")}</p>
        ) : null}
        <StatsTableView
          table={table}
          definitions={metadata.stat_defs}
          empty={activeSegment === 0 && activeEntity === TOTALS ? "members" : "values"}
        />
      </TabsContent>

      <TabsContent value="timeline">
        <MatchEventsTimeline match={match} eventTypes={metadata.event_types} />
      </TabsContent>
    </Tabs>
  );
}

/**
 * The statistics of one match: the discipline's own scoreboard when its module has one for this shape (a duel),
 * the generic table of the declared stats otherwise. The match's own game (`workspace_id` + `discipline`)
 * decides — never the page's browsing game.
 */
export default function MatchStatistics({ match }: Readonly<{ match: MatchWithStats }>) {
  const metadata = useDisciplineMetadata(match.workspace_id, match.discipline);

  if (metadata.isPending) return <Skeleton className="h-64 w-full rounded-lg" />;
  if (metadata.isError)
    return <PageStateCard state="error" onAction={() => void metadata.refetch()} />;

  return (
    <DisciplineWidget
      discipline={match.discipline}
      load={loadMatchUI}
      slot="matchStats"
      capabilities={metadata.data.discipline.capabilities}
      applicable={match.participants.length === 2}
      props={{ match, metadata: metadata.data }}
      fallback={<GenericMatchStatistics match={match} metadata={metadata.data} />}
    />
  );
}
