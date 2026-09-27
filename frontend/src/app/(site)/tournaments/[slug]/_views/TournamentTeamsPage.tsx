"use client";

import { useMemo } from "react";
import { LayoutGrid, List } from "lucide-react";
import { useTranslations } from "next-intl";

import { TournamentTeamCard } from "@/components/TournamentTeamCard";
import { FilterChip } from "@/components/ui/filter-chip";
import { SearchField } from "@/components/ui/search-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { useQueryParams } from "@/hooks/useQueryParams";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { getPublicPageQueryPresentation } from "@/lib/public-page-query-presentation";
import { isTournamentStatusEnded } from "@/lib/tournament/status";
import { cn } from "@/lib/utils";
import { Tournament } from "@/types/tournament.types";

import { SectionToolbar } from "../_components/SectionToolbar";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentTeamsSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { ViewSegment, readViewParam } from "../_components/ViewSegment";
import { TeamListRow } from "./_components/TeamListRow";
import {
  compareTeams,
  listGrid,
  MARK_CLASS,
  matchesSearch,
  TEAMS_SORTS,
  TEAMS_VIEWS,
  type TeamsSortBy
} from "./tournamentTeams.model";
import { useIsNarrowViewport, useStoredTeamsView, writeStoredView } from "./useTeamsViewPreference";
import { useTournamentTeamsData } from "./useTournamentTeamsData";

const TournamentTeamsView = ({ tournament, slug }: { tournament: Tournament; slug: string }) => {
  const t = useTranslations();
  const { teamsQuery, records, registrationsByUser, heroesMap } =
    useTournamentTeamsData(tournament);

  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const storedView = useStoredTeamsView();
  const narrow = useIsNarrowViewport();
  const withRoles = tournament.roster_shape?.has_role_slots ?? true;

  const teams = useMemo(() => teamsQuery.data?.results ?? [], [teamsQuery.data]);

  const defaultSort: TeamsSortBy = isTournamentStatusEnded(tournament.status)
    ? "placement"
    : "group";
  const sortBy = readViewParam(searchParams, "sort", TEAMS_SORTS, defaultSort);
  const groupFilter = searchParams?.get("group") ?? null;
  const search = searchParams?.get("q") ?? "";
  const needle = search.trim().toLowerCase();
  const view = narrow
    ? "list"
    : readViewParam(searchParams, "view", TEAMS_VIEWS, storedView ?? "list");

  const groups = useMemo(() => {
    const counts = new Map<string, number>();
    for (const team of teams) {
      const name = team.group?.name;
      if (name) counts.set(name, (counts.get(name) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [teams]);

  const visibleTeams = useMemo(
    () =>
      teams
        .filter((team) => groupFilter == null || team.group?.name === groupFilter)
        .filter((team) => matchesSearch(team, needle))
        .sort((a, b) => compareTeams(a, b, sortBy)),
    [teams, groupFilter, needle, sortBy]
  );

  const presentation = getPublicPageQueryPresentation({
    data: teamsQuery.data,
    itemCount: teams.length,
    isPending: teamsQuery.isPending,
    isError: teamsQuery.isError,
    isFetching: teamsQuery.isFetching
  });

  if (presentation.initialState === "error") {
    return <TournamentPageState state="initial-error" onRetry={() => void teamsQuery.refetch()} />;
  }

  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentTeamsSkeleton />;
  }

  const content = (
    <div className="space-y-4">
      {presentation.showUpdating ? <UpdatingBadge /> : null}
      {presentation.contentState === "empty" ? (
        <TournamentPageState state="empty" />
      ) : (
        <>
          <SectionToolbar
            label={t("common.filters")}
            end={
              <>
                <SearchField
                  value={search}
                  onValueChange={(value) => setParams({ q: value || null })}
                  label={t("tournamentDetail.teams.searchLabel")}
                  placeholder={t("tournamentDetail.teams.searchPlaceholder")}
                  containerClassName="w-[11rem]"
                  className="h-8 py-1"
                />
                <Select
                  value={sortBy}
                  onValueChange={(value) => {
                    const next = value as TeamsSortBy;
                    setParams({ sort: next === defaultSort ? null : next });
                  }}
                >
                  <SelectTrigger
                    aria-label={t("tournamentDetail.sortTeams")}
                    className="filter-sort h-8 w-[10.5rem] shadow-none focus:ring-0 focus:ring-offset-0"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="placement">{t("common.byPlacement")}</SelectItem>
                    <SelectItem value="group">{t("tournamentDetail.teams.byGroup")}</SelectItem>
                    <SelectItem value="sr">{t("common.byAvgSr")}</SelectItem>
                    <SelectItem value="name">{t("common.byName")}</SelectItem>
                  </SelectContent>
                </Select>
                <ViewSegment
                  param="view"
                  defaultValue={storedView ?? "list"}
                  options={[
                    {
                      value: "list",
                      label: <List aria-hidden width={14} height={14} />,
                      ariaLabel: t("tournamentDetail.teams.viewList")
                    },
                    {
                      value: "cards",
                      label: <LayoutGrid aria-hidden width={14} height={14} />,
                      ariaLabel: t("tournamentDetail.teams.viewCards")
                    }
                  ]}
                  onChange={(next) => writeStoredView(next)}
                  label={t("tournamentDetail.teams.viewLabel")}
                />
              </>
            }
          >
            <FilterChip
              active={groupFilter == null}
              count={teams.length}
              onClick={() => setParams({ group: null })}
            >
              {t("common.all")}
            </FilterChip>
            {groups.map(([name, count]) => (
              <FilterChip
                key={name}
                active={groupFilter === name}
                count={count}
                onClick={() => setParams({ group: name })}
              >
                {t("common.group")} {name}
              </FilterChip>
            ))}
          </SectionToolbar>

          {visibleTeams.length === 0 ? (
            <TournamentPageState
              state="filtered-empty"
              onReset={() => setParams({ group: null, q: null })}
            />
          ) : view === "cards" ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {visibleTeams.map((team) => {
                const matched =
                  needle === ""
                    ? []
                    : team.players.filter((player) => player.name.toLowerCase().includes(needle));
                return (
                  <div key={team.id} className="space-y-1">
                    {/* Wireframe §5 ⑤ keeps this card byte-for-byte; the matched
                        battletag is therefore marked above it rather than
                        inside `TournamentTeamCard`, which this screen does not
                        own. Nothing renders when nothing was searched, so the
                        card's surroundings are unchanged by default. */}
                    {matched.length > 0 ? (
                      <p className="truncate text-label text-[color:var(--aqt-fg-dim)]">
                        {t("tournamentDetail.teams.matchedPlayers")}{" "}
                        {matched.map((player, index) => (
                          <span key={player.id}>
                            {index > 0 ? ", " : null}
                            <mark className={MARK_CLASS}>{player.name}</mark>
                          </span>
                        ))}
                      </p>
                    ) : null}
                    <TournamentTeamCard team={team} />
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="border-t border-[color:var(--aqt-border)]">
              <div
                className={cn(
                  listGrid(withRoles),
                  "border-b border-[color:var(--aqt-border)] px-2 py-1.5 text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]"
                )}
              >
                <span>#</span>
                <span />
                <span>{t("tournamentDetail.teams.team")}</span>
                <span>{t("teams.roster.avgSr")}</span>
                {withRoles ? (
                  <span className="hidden sm:block">{t("tournamentDetail.teams.rosterColumn")}</span>
                ) : null}
                <span className="text-right">{t("tournamentDetail.teams.record")}</span>
                <span />
              </div>
              {visibleTeams.map((team) => (
                <TeamListRow
                  key={team.id}
                  team={team}
                  tournament={tournament}
                  slug={slug}
                  record={records?.get(team.id) ?? null}
                  needle={needle}
                  registrationsByUser={registrationsByUser}
                  heroesMap={heroesMap}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );

  if (presentation.showRefreshError) {
    return (
      <TournamentPageState
        state="refresh-error"
        onRetry={() => void teamsQuery.refetch()}
        isUpdating={teamsQuery.isFetching}
      >
        {content}
      </TournamentPageState>
    );
  }

  return content;
};

/**
 * Resolves the shared tournament overview so the route file stays a thin
 * server boundary, matching every other tournament sub-route. The overview is
 * hydrated by that boundary, so this is a cache read in practice — the guards
 * below only fire if that contract ever changes.
 */
const TournamentTeamsPage = ({ slug }: { slug: string }) => {
  // Keyed by `slug`: shares TournamentClientLayout's overview cache entry.
  const tournamentQuery = useTournamentQuery(slug);

  if (!tournamentQuery.data) {
    if (tournamentQuery.isError) {
      return (
        <TournamentPageState state="initial-error" onRetry={() => void tournamentQuery.refetch()} />
      );
    }
    return <TournamentTeamsSkeleton />;
  }

  return <TournamentTeamsView tournament={tournamentQuery.data} slug={slug} />;
};

export default TournamentTeamsPage;
