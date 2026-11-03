"use client";

import { useMemo, useState } from "react";
import { ChevronUp, Crown, Lock } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { HandleLabel } from "@/components/HandleLabel";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { CELL, CUT_LINE, MapDiff, ROW_TINT } from "@/components/StandingsTable";
import { Card } from "@/components/ui/card";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import { SearchField } from "@/components/ui/search-field";
import { TableCell, TableRow } from "@/components/ui/table";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { useFormatter } from "@/lib/datetime/client";
import { getPublicPageQueryPresentation } from "@/lib/public-page-query-presentation";
import { roleColor } from "@/lib/roster/ontology";
import { cn } from "@/lib/utils";
import type { PlayerStanding, Tournament } from "@/types/tournament.types";

import { SectionToolbar } from "../_components/SectionToolbar";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentRankingSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { playerStandingsQueryOptions } from "../_queries/individualSwiss";
import { SortableTable, type SortableColumn } from "./_components/SortableTable";
import { orderPlayerStandings, playerStandingsCutAfter } from "./playerStandings.model";

const TournamentRankingView = ({ tournament }: { tournament: Tournament }) => {
  const t = useTranslations();
  const tRoles = useTranslations("common.roles");
  const format = useFormatter();
  const standingsQuery = useQuery(playerStandingsQueryOptions(tournament));
  const ontology =
    useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;

  const [stageChoice, setStageChoice] = useState<number | null>(null);
  const [role, setRole] = useState("all");
  const [query, setQuery] = useState("");

  const data = useMemo(() => standingsQuery.data ?? [], [standingsQuery.data]);
  const rows = useMemo(() => orderPlayerStandings(data), [data]);
  // First appearance in the API's order: stages in order, roles in roster-shape order.
  const stageIds = useMemo(() => [...new Set(data.map((row) => row.stage_id))], [data]);
  const roles = useMemo(() => [...new Set(data.map((row) => row.role))], [data]);
  const stageNames = useMemo(
    () => new Map(tournament.stages.map((stage) => [stage.id, stage.name])),
    [tournament.stages]
  );
  // A player sits in every stage's table, so stages never mix; the latest one shows first.
  const stageId =
    stageChoice != null && stageIds.includes(stageChoice) ? stageChoice : stageIds.at(-1);
  const stageRows = rows.filter((row) => row.stage_id === stageId);
  const roleCounts = new Map<string, number>();
  for (const row of stageRows) roleCounts.set(row.role, (roleCounts.get(row.role) ?? 0) + 1);
  const needle = query.trim().toLowerCase();
  const visible = stageRows.filter(
    (row) =>
      (role === "all" || row.role === role) &&
      (needle === "" || row.display_name.toLowerCase().includes(needle))
  );
  // Places and the cut count inside a role, so the line only means something in one role's table.
  const cutAfter = role === "all" ? null : playerStandingsCutAfter(visible);

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

  const roleLabel = (code: string) => (tRoles.has(code as never) ? tRoles(code as never) : code);
  const pinnedTitle = t("standings.pinnedPlace");
  const qualifiedTitle = t("tournamentDetail.ranking.qualified");
  // One decimal for every row once any score is fractional, so the column lines up; none for whole-point scoring.
  const pointDigits = stageRows.some((row) => !Number.isInteger(row.points)) ? 1 : 0;

  const columns: SortableColumn<PlayerStanding>[] = [
    {
      key: "position",
      label: "#",
      sortValue: (row) => row.position,
      ascendingFirst: true,
      className: "w-12 whitespace-nowrap sm:w-16",
      cell: (row) => (
        <span className="inline-flex items-center gap-0.5">
          <span
            className={cn(
              "inline-block min-w-6 font-display text-title leading-none font-extrabold tabular-nums",
              row.is_qualified ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-faint)]"
            )}
          >
            {row.position ?? "\u2014"}
          </span>
          {/* Qualifying is said by a shape too, not by the teal alone. */}
          {row.is_qualified ? (
            <IconTooltip label={qualifiedTitle}>
              {/* Stroke follows the extrabold place beside it. */}
              <ChevronUp
                aria-hidden
                strokeWidth={2.75}
                className="size-3.5 text-[color:var(--aqt-teal)]"
              />
            </IconTooltip>
          ) : null}
          {row.is_pinned ? (
            <IconTooltip label={pinnedTitle}>
              <Lock aria-hidden className="size-3 text-[color:var(--aqt-fg-dim)]" />
            </IconTooltip>
          ) : null}
        </span>
      )
    },
    {
      key: "player",
      label: t("tournamentDetail.ranking.player"),
      sortValue: (row) => row.display_name.toLowerCase(),
      ascendingFirst: true,
      // Takes the width the numbers leave, so they sit tight against the right edge.
      className: "w-full",
      cell: (row) => (
        <span className="flex min-w-0 items-center gap-2.5">
          <PlayerRoleIcon
            role={row.role}
            ontology={ontology}
            size={16}
            label={roleLabel(row.role)}
          />
          <HandleLabel
            handle={row.display_name}
            title={row.display_name}
            className="max-w-[12rem] text-body font-semibold text-[color:var(--aqt-fg)] sm:max-w-[18rem]"
          />
          {row.is_captain ? (
            <IconTooltip label={t("tournamentDetail.ranking.captain")} className="shrink-0">
              <Crown aria-hidden className="size-3.5 text-[color:var(--aqt-amber)]" />
            </IconTooltip>
          ) : null}
        </span>
      )
    },
    {
      key: "points",
      label: t("standings.colPts"),
      title: t("common.tiebreakerMetrics.points"),
      sortValue: (row) => row.points,
      numeric: true,
      className: "w-16 whitespace-nowrap",
      cell: (row) => (
        <span className="text-body font-semibold text-[color:var(--aqt-fg)]">
          {format.number(row.points, {
            minimumFractionDigits: pointDigits,
            maximumFractionDigits: pointDigits
          })}
        </span>
      )
    },
    {
      key: "wdl",
      label: t("standings.colWDL"),
      numeric: true,
      className: "w-24 whitespace-nowrap max-sm:hidden",
      cell: (row) => (
        <span className="inline-flex items-baseline gap-1 text-body font-semibold">
          <span className="text-[color:var(--aqt-emerald)]">{row.wins}</span>
          <span className="text-[color:var(--aqt-fg-faint)]">·</span>
          <span className="text-[color:var(--aqt-amber)]">{row.draws}</span>
          <span className="text-[color:var(--aqt-fg-faint)]">·</span>
          <span className="text-[color:var(--aqt-fg-dim)]">{row.losses}</span>
        </span>
      )
    },
    {
      key: "map_diff",
      label: t("standings.colMapDiff"),
      title: t("common.scoreDiff"),
      sortValue: (row) => row.map_diff,
      numeric: true,
      className: "w-20 whitespace-nowrap max-sm:hidden",
      cell: (row) => <MapDiff diff={row.map_diff} />
    },
    {
      key: "buchholz",
      label: t("common.buchholz"),
      sortValue: (row) => row.buchholz,
      numeric: true,
      className: "w-24 whitespace-nowrap max-sm:hidden",
      cell: (row) => (
        <span className="text-[color:var(--aqt-fg-dim)]">
          {format.number(row.buchholz, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
        </span>
      )
    }
  ];

  const resetFilters = () => {
    setRole("all");
    setQuery("");
  };

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
        <>
          <SectionToolbar
            label={t("common.filters")}
            end={
              <SearchField
                value={query}
                onValueChange={setQuery}
                label={t("tournamentDetail.ranking.search")}
                placeholder={t("tournamentDetail.ranking.searchPlaceholder")}
                containerClassName="w-[11rem]"
                className="py-1"
              />
            }
          >
            {stageIds.length > 1 ? (
              <FilterChipGroup
                label={t("tournamentDetail.ranking.stageFilter")}
                className="flex-nowrap"
              >
                {stageIds.map((id) => (
                  <FilterChip key={id} active={id === stageId} onClick={() => setStageChoice(id)}>
                    {stageNames.get(id) ?? id}
                  </FilterChip>
                ))}
              </FilterChipGroup>
            ) : null}
            {roles.length > 1 ? (
              <FilterChipGroup
                label={t("tournamentDetail.ranking.roleFilter")}
                className="flex-nowrap"
              >
                <FilterChip
                  active={role === "all"}
                  count={stageRows.length}
                  onClick={() => setRole("all")}
                >
                  {t("common.all")}
                </FilterChip>
                {roles.map((item) => (
                  <FilterChip
                    key={item}
                    active={role === item}
                    count={roleCounts.get(item) ?? 0}
                    accent={roleColor(ontology, item) ?? undefined}
                    onClick={() => setRole(item)}
                  >
                    <PlayerRoleIcon role={item} ontology={ontology} size={14} decorative />
                    {roleLabel(item)}
                  </FilterChip>
                ))}
              </FilterChipGroup>
            ) : null}
          </SectionToolbar>

          {visible.length === 0 ? (
            <TournamentPageState state="filtered-empty" onReset={resetFilters} />
          ) : (
            <Card className="min-w-0 overflow-hidden">
              <SortableTable
                rows={visible}
                columns={columns}
                rowKey={(row) => row.workspace_member_id}
                defaultSort={{ key: "position", ascending: true }}
                label={t("tournamentDetail.ranking.title")}
                empty={t("tournamentDetail.pageState.filteredEmpty.title")}
                pageSize={25}
                numbered={false}
                rowClassName={(row) => cn("[&>td]:py-2.5", row.is_qualified && ROW_TINT.advance)}
                rowAfter={(row, sort) =>
                  row.workspace_member_id === cutAfter &&
                  sort.key === "position" &&
                  sort.ascending ? (
                    <TableRow>
                      <TableCell
                        colSpan={columns.length}
                        className={cn(CELL, CUT_LINE)}
                        data-cut="playoff"
                        data-label={t("tournamentDetail.ranking.cutLine")}
                      />
                    </TableRow>
                  ) : null
                }
              />
            </Card>
          )}
        </>
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
