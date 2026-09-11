import { announcementHref } from "@/lib/announcement-text";
import { tournamentHref } from "@/lib/tournament-url";
import type { NotificationItem } from "@/types/notification.types";

function isId(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

/** System destinations come from known routes, never an arbitrary payload href. */
export function notificationHref(item: NotificationItem): string | null {
  const { kind, payload } = item;

  switch (kind) {
    case "announcement.published":
      return announcementHref(payload);
    case "team_invite.received":
    case "registration.approved":
    case "registration.rejected":
    case "team.kicked":
    case "team.rejected":
    case "team.disbanded":
      return isId(payload.tournament_id)
        ? tournamentHref(payload.tournament_id, "/participants")
        : null;
    case "encounter.report_disputed":
      return isId(payload.tournament_id) && isId(payload.encounter_id)
        ? tournamentHref(payload.tournament_id, `/pregame/${payload.encounter_id}`)
        : null;
    // An answered invite has only a pre-formation team ID, not a tournament
    // reference. It cannot link to the unrelated post-balancer team routes.
    case "team_invite.answered":
    default:
      return null;
  }
}
