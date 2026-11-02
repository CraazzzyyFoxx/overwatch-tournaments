"use client";

import React, { useMemo } from "react";
import { Crown } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { CELL, CUT_LINE, HEAD } from "@/components/StandingsTable";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { getPublicPageQueryPresentation } from "@/lib/public-page-query-presentation";
import { cn } from "@/lib/utils";
import type { Tournament } from "@/types/tournament.types";

import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentRankingSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { playerStandingsQueryOptions } from "../_queries/individualSwiss";
import { groupPlayerStandings } from "./playerStandings.model";

/** `+2`, `−1`, `0`: the sign is the fact, so a zero stays unsigned. */
function signed(value: number): string {
  return value > 0 ? `+${value}` : value < 0 ? `\u2212${-value}` : "0";
}

const TournamentRankingView = ({ tournament }: { tournament: Tournament }) => {
  const t = useTranslations();
  const tRoles = useTranslations("common.roles");
  const standingsQuery = useQuery(playerStandingsQueryOptions(tournament));
  const ontology =
    useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;

  const rows = useMemo(() => standingsQuery.data ?? [], [standingsQuery.data]);
  const groups = useMemo(() => groupPlayerStandings(rows), [rows]);
  const stageNames = useMemo(
    () => new Map(tournament.stages.map((stage) => [stage.id, stage.name])),
    [tournament.stages]
  );
  const showStage = new Set(groups.map((group) => group.stageId)).size > 1;

  const presentation = getPublicPageQueryPresentation({
    data: standingsQuery.data,
    itemCount: rows.length,
    isPending: standingsQuery.isPending,
    isError: standingsQuery.isError,
    isFetching: standingsQuery.isFetching
  });

  if (presentation.initialState === "error") {
    return (
      <TournamentPageState state="initial-error" onRetry={() => void standingsQuery.refetch()} />
    );
  }
  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentRankingSkeleton />;
  }

  const roleLabel = (role: string) =>
    tRoles.has(role as never) ? tRoles(role as never) : role;

  const content = (
    <div className="space-y-4">
      {presentation.showUpdating ? <UpdatingBadge /> : null}
      {presentation.contentState === "empty" ? (
        <TournamentPageState
          state="empty"
          title={t("tournamentDetail.ranking.empty.title")}
          description={t("tournamentDetail.ranking.empty.description")}
        />
      ) : (
        groups.map((group) => {
          const name = roleLabel(group.role);
          return (
            <Card key={group.key} asChild className="overflow-hidden">
              <section
                aria-label={t("tournamentDetail.ranking.tableLabel", { role: name })}
                className="min-w-0"
              >
                <h2 className="flex items-center gap-2 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-4 py-3 text-ui font-semibold">
                  <PlayerRoleIcon role={group.role} ontology={ontology} size={18} decorative />
                  {name}
                  {showStage ? (
                    <span className="font-normal text-[color:var(--aqt-fg-dim)]">
                      {stageNames.get(group.stageId)}
                    </span>
                  ) : null}
                </h2>
                <Table className="min-w-120">
                  <TableHeader>
                    <TableRow>
                      <TableHead scope="col" className={HEAD} style={{ width: 52 }}>
                        #
                      </TableHead>
                      <TableHead scope="col" className={HEAD}>
                        {t("tournamentDetail.ranking.player")}
                      </TableHead>
                      <TableHead scope="col" className={cn(HEAD, "text-right")} style={{ width: 64 }}>
                        {t("standings.colPts")}
                      </TableHead>
                      <TableHead scope="col" className={cn(HEAD, "text-center")} style={{ width: 84 }}>
                        {t("standings.colWDL")}
                      </TableHead>
                      <TableHead scope="col" className={cn(HEAD, "text-right")} style={{ width: 72 }}>
                        {t("standings.colMapDiff")}
                      </TableHead>
                      <TableHead scope="col" className={cn(HEAD, "text-right")} style={{ width: 84 }}>
                        {t("common.buchholz")}
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {group.rows.map((row, index) => (
                      <React.Fragment key={row.workspace_member_id}>
                        <TableRow>
                          <TableCell
                            className={cn(
                              CELL,
                              "font-display text-title leading-none font-extrabold tabular-nums",
                              row.is_qualified
                                ? "text-[color:var(--aqt-teal)]"
                                : "text-[color:var(--aqt-fg-faint)]"
                            )}
                          >
                            {row.position ?? "\u2014"}
                            {row.is_qualified ? (
                              <span className="sr-only">{t("tournamentDetail.ranking.qualified")}</span>
                            ) : null}
                          </TableCell>
                          <TableCell className={cn(CELL, "max-w-0 truncate font-medium")}>
                            <bdi>{row.display_name}</bdi>
                            {row.is_captain ? (
                              <>
                                <Crown
                                  aria-hidden
                                  className="ml-1 inline-block size-3 align-[-1px] text-[color:var(--aqt-amber)]"
                                />
                                <span className="sr-only">{t("tournamentDetail.ranking.captain")}</span>
                              </>
                            ) : null}
                          </TableCell>
                          <TableCell className={cn(CELL, "text-right font-semibold tabular-nums")}>
                            {row.points}
                          </TableCell>
                          <TableCell className={cn(CELL, "text-center tabular-nums")}>
                            <span className="text-[color:var(--aqt-emerald)]">{row.wins}</span>
                            <span className="text-[color:var(--aqt-fg-faint)]"> · </span>
                            <span className="text-[color:var(--aqt-amber)]">{row.draws}</span>
                            <span className="text-[color:var(--aqt-fg-faint)]"> · </span>
                            <span className="text-[color:var(--aqt-fg-dim)]">{row.losses}</span>
                          </TableCell>
                          <TableCell
                            className={cn(CELL, "text-right tabular-nums text-[color:var(--aqt-fg-muted)]")}
                          >
                            {signed(row.map_diff)}
                          </TableCell>
                          <TableCell
                            className={cn(CELL, "text-right tabular-nums text-[color:var(--aqt-fg-dim)]")}
                          >
                            {row.buchholz.toFixed(1)}
                          </TableCell>
                        </TableRow>
                        {group.cutAfter === index ? (
                          <TableRow>
                            <TableCell
                              colSpan={6}
                              className={cn(CELL, CUT_LINE)}
                              data-cut="playoff"
                              data-label={t("tournamentDetail.ranking.cutLine")}
                            />
                          </TableRow>
                        ) : null}
                      </React.Fragment>
                    ))}
                  </TableBody>
                </Table>
              </section>
            </Card>
          );
        })
      )}
    </div>
  );

  return presentation.showRefreshError ? (
    <TournamentPageState state="refresh-error" onRetry={() => void standingsQuery.refetch()}>
      {content}
    </TournamentPageState>
  ) : (
    content
  );
};

/** Resolves the shared tournament overview, like every other tab view. */
const TournamentRankingPage = ({ slug }: { slug: string }) => {
  const tournamentQuery = useTournamentQuery(slug);

  if (!tournamentQuery.data) {
    if (tournamentQuery.isError) {
      return (
        <TournamentPageState state="initial-error" onRetry={() => void tournamentQuery.refetch()} />
      );
    }
    return <TournamentRankingSkeleton />;
  }

  return <TournamentRankingView tournament={tournamentQuery.data} />;
};

export default TournamentRankingPage;
