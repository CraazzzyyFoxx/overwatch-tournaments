"use client";

import { useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Card } from "@/components/ui/card";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import LabelledSelect from "@/components/match/LabelledSelect";
import StatsTableView from "@/components/match/StatsTable";
import { DisciplineWidget } from "@/disciplines/DisciplineWidget";
import { loadMatchUI } from "@/disciplines/registry/match";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import encounterService from "@/services/encounter.service";
import type { MatchWithStats } from "@/types/encounter.types";
import type { DisciplineMetadata } from "@/types/discipline.types";
import { buildSeriesTable, memberEntities } from "@/lib/stats/table";
import { CARD_SUB, CardHead } from "@/components/match/EncounterAtoms";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

interface EncounterSeriesStatsProps {
  matchIds: number[];
  /** `overview`: compare observed sides; `players`: totals grouped by participation. */
  view: "overview" | "players";
}

export default function EncounterSeriesStats({
  matchIds,
  view
}: Readonly<EncounterSeriesStatsProps>) {
  const t = useTranslations();

  const queries = useQueries({
    queries: matchIds.map((id) => ({
      queryKey: encounterQueryKeys.matchDetail(id),
      queryFn: () => encounterService.getMatch(id),
      staleTime: 5 * 60_000
    }))
  });

  const loaded = queries
    .map((query) => query.data)
    .filter((data): data is MatchWithStats => data != null);
  const isLoading = queries.some((query) => query.isPending);
  const failedAll = queries.length > 0 && queries.every((query) => query.isError);

  // One encounter is one game: its first loaded observation names the owner and discipline every other one has.
  const owner = loaded[0];
  const metadata = useDisciplineMetadata(owner?.workspace_id ?? "all", owner?.discipline ?? null);

  if (failedAll || metadata.isError) {
    return (
      <PageStateCard
        state="error"
        onAction={() => {
          queries.forEach((query) => void query.refetch());
          if (metadata.isError) void metadata.refetch();
        }}
      />
    );
  }

  if (!owner) {
    return isLoading ? <SeriesStatsSkeleton /> : <PageStateCard state="empty" />;
  }
  if (!metadata.data) return <SeriesStatsSkeleton />;

  const partial = loaded.length < matchIds.length;

  return (
    <div className="flex flex-col gap-3.5">
      {partial ? (
        <Card asChild className="block p-4.5 text-label leading-normal text-[color:var(--aqt-fg-dim)]">
          <output>
            {t("encounters.detail.statsPartial", {
              counted: loaded.length,
              total: matchIds.length
            })}
          </output>
        </Card>
      ) : null}

      <DisciplineWidget
        discipline={owner.discipline}
        load={loadMatchUI}
        slot="seriesStats"
        capabilities={metadata.data.discipline.capabilities}
        applicable={loaded.every((match) => match.participants.length === 2)}
        props={{ matches: loaded, metadata: metadata.data, view }}
        fallback={<GenericSeriesStatistics matches={loaded} metadata={metadata.data} />}
      />
    </div>
  );
}

/**
 * The game-neutral series totals: each stat folded across the maps by its declared aggregation, grouped by
 * participation, for any number of participants, at the member totals or one character's rows (never both
 * added).
 */
function GenericSeriesStatistics({
  matches,
  metadata
}: Readonly<{ matches: MatchWithStats[]; metadata: DisciplineMetadata }>) {
  const t = useTranslations();
  const [entity, setEntity] = useState("none");
  const entities = useMemo(() => memberEntities(matches, 0), [matches]);
  const active = entities.some((candidate) => String(candidate.id) === entity)
    ? Number(entity)
    : "none";
  const table = buildSeriesTable(matches, metadata.stat_defs, active);

  return (
    <Card className="overflow-hidden">
      <CardHead title={t("encounters.detail.seriesTableTitle")}>
        <span className={CARD_SUB}>{t("encounters.detail.seriesTableSub")}</span>
      </CardHead>
      {entities.length > 0 ? (
        <div className="px-4 pb-3">
          <LabelledSelect
            label={t("matches.native.grainLabel")}
            value={String(active)}
            onValueChange={setEntity}
            options={[
              { value: "none", label: t("matches.native.grainTotals") },
              ...entities.map((candidate) => ({
                value: String(candidate.id),
                label: candidate.name
              }))
            ]}
          />
        </div>
      ) : null}
      <StatsTableView
        table={table}
        definitions={metadata.stat_defs}
        withMaps
        empty={active === "none" ? "members" : "values"}
      />
    </Card>
  );
}

function SeriesStatsSkeleton() {
  return (
    <div className="flex flex-col gap-3.5" aria-busy>
      <Skeleton className="h-[68px] w-full" />
      <div className="grid grid-cols-1 items-start gap-3.5 xl:grid-cols-2">
        <Skeleton className="h-[320px] w-full" />
        <Skeleton className="h-[320px] w-full" />
      </div>
      <Skeleton className="h-[120px] w-full" />
      <Skeleton className="h-[420px] w-full" />
    </div>
  );
}

export type { EncounterSeriesStatsProps };
