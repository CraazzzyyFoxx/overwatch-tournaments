import { withReturnTo } from "@/lib/auth/return-to";

/**
 * The pre-game room of one encounter, with the way back baked in.
 *
 * The room's route segment is the tournament *slug*, but a numeric id resolves
 * the same way — the notification renderer has always linked rooms as
 * `/tournaments/{tournament_id}/pregame/{encounter_id}` — so admin callers do
 * not have to carry a slug they rarely hold.
 *
 * `from` comes back out through `safeReturnPath`, which keeps any same-origin
 * path, `/admin/...` included: an organizer sent into a room lands back on the
 * list they came from rather than on the public encounter page.
 */
export function pregameRoomHref(
  tournamentId: number,
  encounterId: number,
  from: string
): string {
  return withReturnTo(`/tournaments/${tournamentId}/pregame/${encounterId}`, from);
}
