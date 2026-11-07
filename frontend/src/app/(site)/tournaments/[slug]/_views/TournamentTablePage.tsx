"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { LeaderboardTable } from "@/components/flow/LeaderboardTable";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useQueryParams } from "@/hooks/useQueryParams";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { buildLeaderboardTable } from "@/lib/flow/leaderboardTable";
import { orderedRoleCodes } from "@/lib/roster/ontology";
import type { Tournament } from "@/types/tournament.types";

import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentRankingSkeleton } from "../_components/TournamentSkeletons";
import { flowQueryOptions } from "../_queries/flow";

const TournamentTableView = ({ tournament }: { tournament: Tournament }) => {
  const t = useTranslations("tournamentDetail.table");
  const flowQuery = useQuery(flowQueryOptions(tournament));
  const metadata = useDisciplineMetadata(tournament.workspace_id, tournament.discipline);
  const ontology = metadata.data ?? null;
  const table = useMemo(
    () =>
      flowQuery.data
        ? buildLeaderboardTable(flowQuery.data, undefined, (codes) => orderedRoleCodes(ontology, codes))
        : null,
    [flowQuery.data, ontology]
  );
  // The view is shareable: role tab, search and sort live in the query string (replaced, never pushed).
  const { searchParams, setParams } = useQueryParams({ shallow: true });
  const params = useMemo(
    () => ({
      role: searchParams?.get("role") ?? null,
      q: searchParams?.get("q") ?? null,
      sort: searchParams?.get("sort") ?? null,
      dir: searchParams?.get("dir") ?? null
    }),
    [searchParams]
  );

  if (flowQuery.isError && !flowQuery.data) {
    return <TournamentPageState state="initial-error" onRetry={() => void flowQuery.refetch()} />;
  }
  // The role dictionary orders the role tabs: rendering before it lands would open, then swap, the default tab.
  if (!flowQuery.data || metadata.isLoading) return <TournamentRankingSkeleton />;
  if (!table || table.rows.length === 0) {
    return <TournamentPageState state="empty" title={t("empty")} />;
  }

  return (
    <Card className="min-w-0 overflow-hidden">
      <div className="flex items-center gap-3 px-4.5 pt-4">
        <h2 className="font-display text-title font-bold">{t("title")}</h2>
        {table.final ? null : (
          <Badge tone="warning" voice="label" size="sm">
            {t("livePreview")}
          </Badge>
        )}
      </div>
      <LeaderboardTable table={table} ontology={ontology} params={params} onParamsChange={setParams} />
    </Card>
  );
};

/** Resolves the shared tournament overview, like every other tab view. */
const TournamentTablePage = ({ slug }: { slug: string }) => {
  const tournamentQuery = useTournamentQuery(slug);

  if (!tournamentQuery.data) {
    if (tournamentQuery.isError) {
      return (
        <TournamentPageState state="initial-error" onRetry={() => void tournamentQuery.refetch()} />
      );
    }
    return <TournamentRankingSkeleton />;
  }

  return <TournamentTableView tournament={tournamentQuery.data} />;
};

export default TournamentTablePage;
