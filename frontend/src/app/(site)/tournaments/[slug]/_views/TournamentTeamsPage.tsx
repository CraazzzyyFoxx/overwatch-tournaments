"use client";

import { useMemo } from "react";
import { LayoutGrid, List } from "lucide-react";
import { useTranslations } from "next-intl";

import { TournamentTeamCard } from "@/components/TournamentTeamCard";
import { FilterChip } from "@/components/ui/filter-chip";
import { Eyebrow } from "@/components/ui/eyebrow";
import { SearchField } from "@/components/ui/search-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useQueryParams } from "@/hooks/useQueryParams";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { getPublicPageQueryPresentation } from "@/lib/public-page-query-presentation";
import { groupDisplayName } from "@/lib/tournament/group";
import { isTournamentStatusEnded } from "@/lib/tournament/status";
import { Tournament } from "@/types/tournament.types";

import { SectionToolbar } from "../_components/SectionToolbar";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentTeamsSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { ViewSegment, readViewParam } from "../_components/ViewSegment";
import { TeamListRow } from "./_components/TeamListRow";
import {
  compareTeams,
  MARK_CLASS,
  matchesSearch,
  TEAMS_SORTS,
  TEAMS_VIEWS,
  type TeamsSortBy
} from "./tournamentTeams.model";
import { overviewVariant } from "./tournamentOverview.model";
import { useIsNarrowViewport, useStoredTeamsView, writeStoredView } from "./useTeamsViewPreference";
import { useTournamentTeamsData } from "./useTournamentTeamsData";

const TournamentTeamsView = ({ tournament, slug }: { tournament: Tournament; slug: string }) => {
  const t = useTranslations();
  const { teamsQuery, records, registrationsByUser, heroesMap } =
    useTournamentTeamsData(tournament);
  // The tournament's own game names and draws every role of the roster.
  const ontology = useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;

  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const storedView = useStoredTeamsView();
  const narrow = useIsNarrowViewport();

  const teams = useMemo(() => teamsQuery.data?.results ?? [], [teamsQuery.data]);

  const groups = useMemo(() => {
    const counts = new Map<string, number>();
    for (const team of teams) {
      const name = team.group?.name;
      if (name) counts.set(name, (counts.get(name) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [teams]);

  // A sort that cannot reorder anything is not offered.
  const hasPlacement = teams.some((team) => team.placement != null);
  const sortOptions = TEAMS_SORTS.filter(
    (sort) => (sort !== "placement" || hasPlacement) && (sort !== "group" || groups.length > 1)
  );
  const preferredSort: TeamsSortBy = isTournamentStatusEnded(tournament.status)
    ? "placement"
    : "group";
  const defaultSort = sortOptions.includes(preferredSort) ? preferredSort : sortOptions[0];
  const sortBy = readViewParam(searchParams, "sort", sortOptions, defaultSort);
  const sortLabel: Record<TeamsSortBy, string> = {
    placement: t("common.byPlacement"),
    group: t("tournamentDetail.teams.byGroup"),
    sr: t("common.byAvgSr"),
    name: t("common.byName")
  };
  const groupFilter = searchParams?.get("group") ?? null;
  const search = searchParams?.get("q") ?? "";
  const needle = search.trim().toLowerCase();
  const view = narrow
    ? "list"
    : readViewParam(searchParams, "view", TEAMS_VIEWS, storedView ?? "list");

  // A group chip whose count equals the total filters nothing.
  const groupChips = groups.filter(([, count]) => count !== teams.length);
  // The group colour only says something when the visible rows mix groups.
  const showGroup = groupFilter == null && groups.length > 1;
  const medal = overviewVariant(tournament.status) === "completed";

  const visibleTeams = teams
    .filter((team) => groupFilter == null || team.group?.name === groupFilter)
    .filter((team) => matchesSearch(team, needle))
    .sort((a, b) => compareTeams(a, b, sortBy));

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
                  className="py-1"
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
                    size="sm"
                    className="w-[10.5rem]"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {sortOptions.map((sort) => (
                      <SelectItem key={sort} value={sort}>
                        {sortLabel[sort]}
                      </SelectItem>
                    ))}
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
            {groupChips.length > 0 ? (
              <>
                <FilterChip
                  active={groupFilter == null}
                  count={teams.length}
                  onClick={() => setParams({ group: null })}
                >
                  {t("common.all")}
                </FilterChip>
                {groupChips.map(([name, count]) => (
                  <FilterChip
                    key={name}
                    active={groupFilter === name}
                    count={count}
                    onClick={() => setParams({ group: name })}
                  >
                    {groupDisplayName(name, t("common.group"))}
                  </FilterChip>
                ))}
              </>
            ) : null}
          </SectionToolbar>

          <Eyebrow as="h2">{t("common.teams")}</Eyebrow>

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
                    <TournamentTeamCard
                      team={team}
                      medal={medal}
                      showGroup={showGroup}
                      discipline={tournament.discipline}
                      ontology={ontology}
                    />
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="space-y-2">
              {visibleTeams.map((team) => (
                <TeamListRow
                  key={team.id}
                  team={team}
                  tournament={tournament}
                  slug={slug}
                  record={records?.get(team.id) ?? null}
                  needle={needle}
                  showGroup={showGroup}
                  registrationsByUser={registrationsByUser}
                  heroesMap={heroesMap}
                  ontology={ontology}
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
