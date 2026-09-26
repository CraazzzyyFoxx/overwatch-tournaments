"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { tournamentTeamsQueryOptions } from "@/lib/tournament/teams-query";
import encounterService from "@/services/encounter.service";
import registrationService from "@/services/registration.service";
import type { Registration } from "@/types/registration.types";
import type { Tournament } from "@/types/tournament.types";

import { useHeroesMap } from "./_components/useHeroesMap";
import { buildRecords, type TeamRecord } from "./tournamentTeams.model";

/**
 * Everything the teams section reads.
 *
 * Only the roster is prefetched by the route: it is the section. The other
 * three are enrichments that each render as a dash until they land, and all
 * three are cache reads for a reader who has already been to the section that
 * owns them.
 */
export function useTournamentTeamsData(tournament: Tournament) {
  const teamsQuery = useQuery(tournamentTeamsQueryOptions(tournament));

  // Same key and same call the bracket and the matches section use, so the
  // W-L column is a cache read wherever the reader has already been.
  const encountersQuery = useQuery({
    queryKey: tournamentQueryKeys.encounters(tournament.id, tournament.workspace_id),
    queryFn: () =>
      encounterService.getAll(
        1,
        "",
        tournament.id,
        -1,
        undefined,
        undefined,
        tournament.workspace_id
      )
  });

  // Declared top heroes for the roster expansion (§5 ③) — the participants
  // section's own list and hero catalogue, so both are cache reads after one
  // visit there. Only draft/balancer tournaments register players one by one;
  // a team-registration read would come back without per-player picks.
  const hasPlayerRegistrations = tournament.team_formation !== "registration";
  const registrationsQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationsList(tournament.workspace_id, tournament.id),
    queryFn: () => registrationService.listRegistrations(tournament.id),
    enabled: hasPlayerRegistrations
  });
  const heroesMap = useHeroesMap({ enabled: hasPlayerRegistrations });

  const registrationsByUser = useMemo(() => {
    const byUser = new Map<number, Registration>();
    // Empty when the organizer hid the participants list; the roster expansion
    // then simply renders without declared heroes.
    for (const registration of registrationsQuery.data?.registrations ?? []) {
      if (registration.user_id !== null) byUser.set(registration.user_id, registration);
    }
    return byUser;
  }, [registrationsQuery.data]);

  const records = useMemo<Map<number, TeamRecord> | null>(() => {
    const encounters = encountersQuery.data?.results;
    return encounters ? buildRecords(encounters) : null;
  }, [encountersQuery.data]);

  return { teamsQuery, records, registrationsByUser, heroesMap };
}
