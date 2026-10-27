"use client";

import { Fragment, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ArrowDown, ArrowUp, ChevronDown, ChevronUp } from "lucide-react";

import { CatalogEntityStrip } from "@/components/catalog/CatalogEntityImage";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import PlayerName from "@/components/PlayerName";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DataPagination } from "@/components/ui/data-pagination";
import { PageStateCard } from "@/components/ui/page-state-card";
import { PlaceBadge } from "@/components/ui/place-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { formatOptional } from "@/app/(site)/users/components/shared/list-utils";
import { cn } from "@/lib/utils";
import type { UserOverviewRow } from "@/types/user.types";
import type { DivisionGrid, DivisionGridVersion } from "@/types/workspace.types";

import { PlayerCard } from "./UsersCatalogView";
import { UserExpandedRow } from "./UserExpandedRow";
import { CompareCheckbox, GameMarks, LastActive, RolesCrests, WinrateCell } from "./users-index.atoms";
import { PER_PAGE_OPTIONS, type SortValue } from "./users-index.model";
import type { CompareSelection } from "./UsersCompareBar";
import type { UsersIndexData } from "./useUsersIndexData";
import type { UsersIndexParamControls } from "./useUsersIndexParams";

/** A sortable column head: a real button inside a `th` that reports `aria-sort`. */
function SortHead({
  sort,
  controls,
  align = "center",
  className,
  children
}: Readonly<{
  sort: SortValue;
  controls: UsersIndexParamControls;
  align?: "start" | "center";
  className?: string;
  children: ReactNode;
}>) {
  const active = controls.params.sort === sort;
  const ascending = controls.params.order === "asc";
  const Arrow = ascending ? ArrowUp : ArrowDown;

  return (
    <TableHead
      scope="col"
      aria-sort={active ? (ascending ? "ascending" : "descending") : "none"}
      className={className}
    >
      <Button
        variant="ghost"
        size="label"
        onClick={() => controls.toggleSort(sort)}
        className={cn(
          "hover:bg-transparent hover:text-[color:var(--aqt-fg)]",
          align === "center" ? "justify-center" : "justify-start",
          active && "text-[color:var(--aqt-teal)]"
        )}
      >
        {children}
        {active ? <Arrow aria-hidden /> : null}
      </Button>
    </TableHead>
  );
}

/** The ranked, paginated player table, with a lazy per-player drawer. */
export function UsersTableView({
  controls,
  data,
  compare,
  onSelectGame
}: Readonly<{
  controls: UsersIndexParamControls;
  data: UsersIndexData;
  compare: CompareSelection;
  /** Narrows the scope to a game (a row's mark under "all games"). */
  onSelectGame: (code: string) => void;
}>) {
  const t = useTranslations();
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set());
  const { page, perPage, minEncounters } = controls.params;
  const { overviewQuery, maxPage, range, workspaceId, discipline } = data;
  const allGames = discipline === null;
  const response = overviewQuery.data;

  const toggleRow = (id: number) =>
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (overviewQuery.isError) {
    return (
      <PageStateCard
        state="error"
        description={(overviewQuery.error as Error)?.message || t("users.list.errors.overview")}
        onAction={() => overviewQuery.refetch()}
      />
    );
  }

  // `isPending`, not `isLoading`: the server never fetches, so there `isLoading`
  // is false and SSR would paint the empty state before the first page lands.
  if (overviewQuery.isPending) {
    return (
      <div className="space-y-2">
        {Array.from({ length: Math.min(perPage, 10) }).map((_, index) => (
          <Skeleton key={`row-skeleton-${index}`} className="h-14 rounded-lg" />
        ))}
      </div>
    );
  }

  if (!response || response.results.length === 0) {
    return (
      <PageStateCard
        state={controls.hasActiveFilters ? "filtered-empty" : "empty"}
        description={t("users.list.empty")}
        onAction={controls.hasActiveFilters ? controls.resetFilters : undefined}
      />
    );
  }

  const firstRank = (response.page - 1) * response.per_page + 1;

  return (
    <section className="space-y-3">
      {/* Below `md` the ten columns cannot be read, so the same rows render as
          the catalog's cards rather than as a horizontally scrolled table. */}
      <div className="grid gap-3 sm:grid-cols-2 md:hidden">
        {response.results.map((user) => (
          <PlayerCard
            key={user.id}
            user={user}
            grids={response.division_grids}
            divisionGrid={controls.divisionGrid}
            game={data}
            minEncounters={minEncounters}
            compare={compare}
            onSelectGame={onSelectGame}
          />
        ))}
      </div>

      <Card className="max-md:hidden overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col" className="w-9 pl-3">
                <span className="sr-only">{t("users.list.compare.column")}</span>
              </TableHead>
              <TableHead scope="col" className="w-10 text-center">
                #
              </TableHead>
              <SortHead sort="name" controls={controls} align="start">
                {t("users.list.table.player")}
              </SortHead>
              <TableHead scope="col" className="text-center">
                {allGames ? t("common.discipline.column") : t("users.list.table.roles")}
              </TableHead>
              <SortHead sort="tournaments_count" controls={controls} className="text-center">
                {t("users.list.table.tournaments")}
              </SortHead>
              <SortHead sort="winrate" controls={controls} className="text-center">
                {t("users.list.table.winrate")}
              </SortHead>
              <SortHead sort="avg_placement" controls={controls} className="text-center">
                {t("users.list.table.avgPlacement")}
              </SortHead>
              <SortHead sort="best_placement" controls={controls} className="text-center">
                {t("users.list.table.bestPlacement")}
              </SortHead>
              <SortHead sort="achievements_count" controls={controls} className="text-center">
                {t("users.list.table.achievements")}
              </SortHead>
              {allGames ? null : (
                <TableHead scope="col" className="text-center">
                  {t("users.list.table.topHeroes")}
                </TableHead>
              )}
              <TableHead scope="col" className="w-10 pr-3">
                <span className="sr-only">{t("users.list.table.details")}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {response.results.map((user, index) => (
              <Fragment key={user.id}>
                <PlayerRow
                  user={user}
                  grids={response.division_grids}
                  divisionGrid={controls.divisionGrid}
                  game={data}
                  rank={firstRank + index}
                  minEncounters={minEncounters}
                  compare={compare}
                  onSelectGame={onSelectGame}
                  expanded={expanded.has(user.id)}
                  onToggle={() => toggleRow(user.id)}
                />
                {expanded.has(user.id) && discipline !== null ? (
                  <TableRow className="bg-[color:var(--aqt-overlay-1)] hover:bg-[color:var(--aqt-overlay-1)]">
                    <TableCell colSpan={11} className="p-0">
                      <UserExpandedRow
                        user={user}
                        workspaceId={workspaceId}
                        discipline={discipline}
                        ontology={data.ontology}
                        compareSelected={compare.isSelected(user.id)}
                        compareDisabled={compare.isFull}
                        onToggleCompare={() => compare.toggle(user)}
                      />
                    </TableCell>
                  </TableRow>
                ) : null}
              </Fragment>
            ))}
          </TableBody>
        </Table>
      </Card>

      <Card className="flex flex-wrap items-center gap-3 p-2.5">
        <span className="text-label tabular-nums text-[color:var(--aqt-fg-faint)]">
          {range
            ? t("users.list.pagination.showingPlayers", {
                start: range.start,
                end: range.end,
                total: response.total
              })
            : null}
          {overviewQuery.isFetching ? ` · ${t("users.list.pagination.refreshing")}` : null}
        </span>

        <ToggleGroup
          variant="pill"
          size="sm"
          value={String(perPage)}
          onValueChange={(next) => next && controls.setPerPage(Number(next))}
          aria-label={t("users.list.pagination.perPage")}
          className="ml-auto"
        >
          {PER_PAGE_OPTIONS.map((option) => (
            <ToggleGroupItem key={option} value={String(option)}>
              {option}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>

        <DataPagination
          page={page}
          totalPages={maxPage}
          onPageChange={(next) => controls.setPage(Math.max(1, Math.min(maxPage, next)))}
        />
      </Card>
    </section>
  );
}

function PlayerRow({
  user,
  grids,
  divisionGrid,
  game,
  rank,
  minEncounters,
  compare,
  expanded,
  onToggle,
  onSelectGame
}: Readonly<{
  user: UserOverviewRow;
  grids: DivisionGridVersion[] | undefined;
  divisionGrid: DivisionGrid;
  game: Pick<UsersIndexData, "discipline" | "ontology">;
  rank: number;
  minEncounters: number;
  compare: CompareSelection;
  expanded: boolean;
  onToggle: () => void;
  onSelectGame: (code: string) => void;
}>) {
  const t = useTranslations();
  const selected = compare.isSelected(user.id);
  const allGames = game.discipline === null;

  return (
    <TableRow>
      <TableCell className="pl-3">
        <CompareCheckbox
          user={user}
          selected={selected}
          disabled={compare.isFull && !selected}
          onToggle={() => compare.toggle(user)}
        />
      </TableCell>
      <TableCell className="text-center text-label tabular-nums text-[color:var(--aqt-fg-faint)]">
        {rank}
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-2.5">
          <PlayerAvatar user={user} size={32} />
          <div className="min-w-0">
            <PlayerName player={{ name: user.name }} className="max-w-[16rem]" />
            <LastActive at={user.last_active_at} />
          </div>
        </div>
      </TableCell>
      <TableCell className="text-center">
        {allGames ? (
          <GameMarks codes={user.disciplines} onSelect={onSelectGame} />
        ) : (
          <RolesCrests
            roles={user.roles}
            grids={grids}
            divisionGrid={divisionGrid}
            discipline={game.discipline}
            ontology={game.ontology}
          />
        )}
      </TableCell>
      <TableCell className="text-center tabular-nums">{user.tournaments_count}</TableCell>
      <TableCell className="text-center">
        <WinrateCell user={user} minEncounters={minEncounters} record={allGames} />
      </TableCell>
      <TableCell className="text-center tabular-nums">
        {formatOptional(user.averages.avg_placement)}
      </TableCell>
      <TableCell className="text-center">
        {user.best_placement ? (
          <PlaceBadge place={user.best_placement} />
        ) : (
          <span className="text-[color:var(--aqt-fg-faint)]">-</span>
        )}
      </TableCell>
      <TableCell className="text-center tabular-nums">{user.achievements_count}</TableCell>
      {allGames ? null : (
        <TableCell>
          <div className="flex justify-center">
            <CatalogEntityStrip entities={user.top_characters.slice(0, 3).map((entry) => entry.character)} limit={3} />
          </div>
        </TableCell>
      )}
      {/* The drawer reads one game's draft card: under "all games" there is nothing to expand. */}
      <TableCell className="pr-3">
        {allGames ? null : (
          <Button
            variant="outline"
            size="icon-sm"
            onClick={onToggle}
            aria-expanded={expanded}
            aria-label={
              expanded ? t("users.list.a11y.collapseDetails") : t("users.list.a11y.expandDetails")
            }
          >
            {expanded ? <ChevronUp aria-hidden /> : <ChevronDown aria-hidden />}
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}
