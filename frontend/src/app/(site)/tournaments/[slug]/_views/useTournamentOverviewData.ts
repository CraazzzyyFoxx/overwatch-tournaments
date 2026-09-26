"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  bracketRoundShape,
  buildRoundGroups,
  orderEliminationRounds
} from "@/lib/bracket/view";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { UNKNOWN_ROUND_SHAPE, type BracketRoundShape } from "@/lib/bracket/round-name";
import { getPublicPageQueryPresentation } from "@/lib/public-page-query-presentation";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import encounterService from "@/services/encounter.service";
import heroService from "@/services/hero.service";
import registrationService from "@/services/registration.service";
import teamService from "@/services/team.service";
import tournamentService from "@/services/tournament.service";

import { useTournamentStreamsQuery } from "../_hooks/useTournamentStreams";
import { getBracketRefetchInterval } from "../bracket/bracketData";
import { buildLiveTeamStreams } from "../bracket/bracketLiveStreams";
import {
  ELIMINATION_TYPES,
  GROUP_TYPES,
  overviewVariant,
  pickOverviewStage
} from "./tournamentOverview.model";

/**
 * Everything the overview reads, in one place: the six queries the three
 * compositions share plus the derivations that hang off more than one of them.
 *
 * Every key and fetcher below is deliberately the same as the page that owns
 * the tab it belongs to, so the overview reuses those cache entries instead of
 * paying for a second copy of the roster, the bracket or the standings.
 */
export function useTournamentOverviewData(tournamentId: number, slug: string) {
  const tournamentQuery = useTournamentQuery(slug);
  const tournament = tournamentQuery.data;
  const variant = tournament ? overviewVariant(tournament.status) : null;
  const workspaceId = tournament?.workspace_id;

  // Memoised for its identity, not its cost: `stageId`/`stageType` below are
  // read off this object and feed the `stageEncounters`/`roundGroups`
  // dependency arrays, and a value re-derived every render is one the compiler
  // has to treat as free to change underneath those memos.
  const stage = useMemo(
    () => (tournament && variant ? pickOverviewStage(tournament.stages, variant) : null),
    [tournament, variant]
  );
  const showsGroupTable =
    variant !== "registration" && stage !== null && GROUP_TYPES[stage.stage_type] === true;
  // A group-only tournament has no bracket to read third place off, so the
  // podium falls back to the standings (plan §5).
  const podiumNeedsStandings =
    variant === "completed" &&
    !(tournament?.stages ?? []).some((item) => ELIMINATION_TYPES[item.stage_type] === true);
  const needsStandings = showsGroupTable || podiumNeedsStandings;
  // Team registration counts teams, not players, so it never reads the roster.
  const needsRegistrations =
    variant === "registration" && tournament?.team_formation !== "registration";

  // Same key and fetcher as `TournamentParticipantsPage`, so the two sections
  // share one cache entry instead of each paying for the roster.
  const registrationsQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationsList(workspaceId ?? 0, tournamentId),
    queryFn: () => registrationService.listRegistrations(tournamentId),
    enabled: tournament !== undefined && needsRegistrations
  });

  // Same key as the bracket's own plan (`bracketData.createBracketQueryPlan`).
  const encountersQuery = useQuery({
    queryKey: tournamentQueryKeys.encounters(tournamentId, workspaceId),
    queryFn: () =>
      encounterService.getAll(1, "", tournamentId, -1, undefined, undefined, workspaceId),
    enabled: tournament !== undefined && variant !== "registration",
    refetchInterval: tournament ? getBracketRefetchInterval(tournament.status) : false,
    refetchIntervalInBackground: false
  });

  // Same key as `TournamentStandingsPage`.
  const standingsQuery = useQuery({
    queryKey: tournamentQueryKeys.standings(tournamentId, workspaceId),
    queryFn: () => tournamentService.getStandings(tournamentId, workspaceId ?? null),
    enabled: tournament !== undefined && needsStandings
  });

  // Same key as `TournamentTeamsPage` — the champion's battletags come off the
  // roster entity, which the encounters read does not carry.
  const teamsQuery = useQuery({
    queryKey: tournamentQueryKeys.teams(tournamentId, workspaceId),
    queryFn: () => teamService.getAll({ tournamentId, workspaceId }),
    enabled: tournament !== undefined && variant === "completed"
  });

  // Same key as `TournamentHeroPlaytimePage`.
  const heroesQuery = useQuery({
    queryKey: tournamentQueryKeys.heroPlaytime(tournamentId),
    queryFn: () => heroService.getHeroPlaytime(1, -1, "all", tournamentId, { workspaceId }),
    enabled: tournament !== undefined && variant === "completed"
  });

  const streamsQuery = useTournamentStreamsQuery(variant === "live" ? tournamentId : undefined);

  const encounters = encountersQuery.data ? encountersQuery.data.results : [];
  const registrationList = registrationsQuery.data ?? null;
  // Empty whenever the organizer hid the list — the summary below still renders,
  // because its numbers ride the same envelope rather than these rows.
  const registrations = registrationList?.registrations ?? [];
  const standings = standingsQuery.data ?? [];
  const teams = teamsQuery.data ? teamsQuery.data.results : [];

  const stageId = stage?.id ?? null;
  const stageEncounters = useMemo(
    () =>
      stageId === null ? [] : encounters.filter((encounter) => encounter.stage_id === stageId),
    [encounters, stageId]
  );
  // Play order (upper → lower → finals), so the window ends on the decider at
  // the right — `buildRoundGroups` interleaves by depth and would put the
  // grand final in the middle of the lower bracket.
  const stageType = stage?.stage_type;
  const roundGroups = useMemo(
    () =>
      stageType !== undefined && ELIMINATION_TYPES[stageType] === true
        ? orderEliminationRounds(stageEncounters, stageType).groups
        : buildRoundGroups(stageEncounters),
    [stageEncounters, stageType]
  );
  // Per stage, because "Latest results" spans stages: a group stage's highest
  // round is not a Grand Final, and naming it one would contradict the bracket.
  const roundShapeByStage = useMemo(() => {
    const byStage: Record<number, BracketRoundShape> = {};
    for (const item of tournament?.stages ?? []) {
      byStage[item.id] = bracketRoundShape(
        item.stage_type,
        encounters.filter((encounter) => encounter.stage_id === item.id)
      );
    }
    return byStage;
  }, [encounters, tournament?.stages]);
  const roundShape =
    (stageId === null ? undefined : roundShapeByStage[stageId]) ?? UNKNOWN_ROUND_SHAPE;

  const liveTeamStreams = useMemo(
    () => buildLiveTeamStreams(streamsQuery.data),
    [streamsQuery.data]
  );

  const stageStandings = stage ? standings.filter((row) => row.stage_id === stage.id) : [];
  // Which of the two stage cards the branch columns get. Booleans rather than
  // "is the element null", because the completed branch falls back to the match
  // block only when neither of them drew anything.
  const hasMiniBracket = stage !== null && !showsGroupTable && roundGroups.length > 0;
  const hasGroupTable = showsGroupTable && stage !== null && stageStandings.length > 0;

  const officialStream = (streamsQuery.data?.official ?? [])[0];
  const participantsOnAir = streamsQuery.data?.participants.length ?? 0;

  const topHeroes = heroesQuery.data
    ? [...heroesQuery.data.results]
        .sort((left, right) => right.playtime - left.playtime)
        .slice(0, 5)
    : [];

  // The primary query per branch: what the page cannot be drawn without.
  const primary =
    variant === "registration" ? (needsRegistrations ? registrationsQuery : null) : encountersQuery;
  const presentation = getPublicPageQueryPresentation({
    // Nothing to wait for when the branch has no primary query: the overview
    // itself is already resolved by the time this runs.
    data: primary === null ? tournament : primary.data,
    itemCount:
      primary === null
        ? 1
        : variant === "registration"
          ? // The count, not the rows: a hidden list ships zero rows and a real
            // total, and an empty state over "48 registered" would be a lie.
            (registrationList?.total ?? registrations.length)
          : encounters.length,
    isPending: primary?.isPending ?? false,
    isError: primary?.isError ?? false,
    isFetching: primary?.isFetching ?? false
  });

  return {
    tournamentQuery,
    tournament,
    variant,
    stage,
    stageId,
    podiumNeedsStandings,
    encounters,
    registrationList,
    registrations,
    standings,
    teams,
    topHeroes,
    stageEncounters,
    stageStandings,
    roundGroups,
    roundShapeByStage,
    roundShape,
    liveTeamStreams,
    hasMiniBracket,
    hasGroupTable,
    officialStream,
    participantsOnAir,
    primary,
    presentation
  };
}
