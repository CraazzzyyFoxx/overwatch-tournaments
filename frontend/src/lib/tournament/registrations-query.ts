import { queryOptions } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import registrationService from "@/services/registration.service";
import type { Tournament } from "@/types/tournament.types";

/**
 * The tournament's registrant roster — the participants section's list, and the
 * declared top heroes the teams section's roster expansion reads.
 *
 * Shared with the Participants route's server prefetch, so both sides build the
 * same key out of one factory.
 */
export function tournamentRegistrationsQueryOptions(
  tournament: Pick<Tournament, "id" | "workspace_id">
) {
  return queryOptions({
    queryKey: tournamentQueryKeys.registrationsList(tournament.workspace_id, tournament.id),
    queryFn: () => registrationService.listRegistrations(tournament.id)
  });
}

/**
 * The form definition that names every column of that roster. Without it the
 * participants table has rows but no columns, so it is a first-paint read too.
 */
export function tournamentRegistrationFormQueryOptions(
  tournament: Pick<Tournament, "id" | "workspace_id">
) {
  return queryOptions({
    queryKey: tournamentQueryKeys.registrationForm(tournament.workspace_id, tournament.id),
    queryFn: () => registrationService.getForm(tournament.id)
  });
}
