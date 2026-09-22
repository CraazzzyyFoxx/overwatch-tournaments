import type { Tournament, TournamentStatus } from "@/types/tournament.types";

// Display text is `common.statusBadge.<status>` in the message catalogs, never here.
type TournamentStatusMeta = {
  /**
   * Which of the four presentation buckets this status falls into. The public
   * tournament surfaces collapse seven statuses into live / upcoming /
   * finished / draft; three files each re-derived that with the same nested
   * ternary. It is a domain fact about the status, so it lives here once.
   */
  variant: "live" | "upcoming" | "finished" | "draft";
  textClassName: string;
  badgeClassName: string;
  dotClassName: string;
  isActive: boolean;
  isEnded: boolean;
};

// Colors mirror `.status-pill.{variant}` in globals.css (draft=blue,
// upcoming=amber, live=rose, finished=dim) so a card and the tournament
// page never disagree about what a status looks like.
const TOURNAMENT_STATUS_META: Record<TournamentStatus, TournamentStatusMeta> = {
  // Announced but not yet open. It shares the amber "upcoming" bucket with
  // registration deliberately: to a visitor both mean "this has not started",
  // and the badge text is what tells them whether they can sign up yet.
  announcement: {
    variant: "upcoming",
    textClassName: "text-[color:var(--aqt-amber)]",
    badgeClassName: "text-[color:var(--aqt-amber)]",
    dotClassName: "bg-[color:var(--aqt-amber)]",
    isActive: true,
    isEnded: false
  },
  draft: {
    variant: "draft",
    textClassName: "text-[color:var(--aqt-blue)]",
    badgeClassName: "text-[color:var(--aqt-blue)]",
    dotClassName: "bg-[color:var(--aqt-blue)]",
    isActive: true,
    isEnded: false
  },
  registration: {
    variant: "upcoming",
    textClassName: "text-[color:var(--aqt-amber)]",
    badgeClassName: "text-[color:var(--aqt-amber)]",
    dotClassName: "bg-[color:var(--aqt-amber)]",
    isActive: true,
    isEnded: false
  },
  check_in: {
    variant: "upcoming",
    textClassName: "text-[color:var(--aqt-amber)]",
    badgeClassName: "text-[color:var(--aqt-amber)]",
    dotClassName: "bg-[color:var(--aqt-amber)]",
    isActive: true,
    isEnded: false
  },
  live: {
    variant: "live",
    textClassName: "text-[color:var(--aqt-rose)]",
    badgeClassName: "text-[color:var(--aqt-rose)]",
    dotClassName: "bg-[color:var(--aqt-rose)]",
    isActive: true,
    isEnded: false
  },
  playoffs: {
    variant: "live",
    textClassName: "text-[color:var(--aqt-rose)]",
    badgeClassName: "text-[color:var(--aqt-rose)]",
    dotClassName: "bg-[color:var(--aqt-rose)]",
    isActive: true,
    isEnded: false
  },
  completed: {
    variant: "finished",
    textClassName: "text-[color:var(--aqt-fg-muted)]",
    badgeClassName: "text-[color:var(--aqt-fg-dim)]",
    dotClassName: "bg-[color:var(--aqt-fg-dim)]",
    isActive: false,
    isEnded: true
  },
  archived: {
    variant: "finished",
    textClassName: "text-[color:var(--aqt-fg-dim)]",
    badgeClassName: "text-[color:var(--aqt-fg-dim)]",
    dotClassName: "bg-[color:var(--aqt-fg-dim)]",
    isActive: false,
    isEnded: true
  }
};

export function getTournamentStatusMeta(status: TournamentStatus) {
  return TOURNAMENT_STATUS_META[status];
}

export function isTournamentStatusActive(status: TournamentStatus) {
  return TOURNAMENT_STATUS_META[status].isActive;
}

export function isTournamentStatusEnded(status: TournamentStatus) {
  return TOURNAMENT_STATUS_META[status].isEnded;
}

export const TOURNAMENT_STATUS_ORDER: TournamentStatus[] = [
  "live",
  "playoffs",
  "registration",
  "check_in",
  "announcement",
  "completed",
  "archived",
  "draft"
];

/**
 * True when the tournament currently sits in `status` and `now` falls inside
 * that phase's schedule row window. A missing row or a `null` ends_at means
 * the window spans the whole phase.
 */
export function isPhaseWindowActive(
  tournament: Pick<Tournament, "status" | "phase_schedule">,
  status: TournamentStatus,
  now: number = Date.now()
) {
  if (tournament.status !== status) return false;

  const row = tournament.phase_schedule?.find((entry) => entry.status === status);
  if (!row) return true;

  const startsAt = new Date(row.starts_at).getTime();
  const endsAt = row.ends_at ? new Date(row.ends_at).getTime() : null;
  return startsAt <= now && (endsAt === null || now <= endsAt);
}

/**
 * Mirrors the backend registration gate (`shared.services.registration_window`):
 * the REGISTRATION phase window plus one override.
 *
 * A MISSING row means closed — deliberately the opposite of
 * `isPhaseWindowActive` above, whose "no row spans the whole phase" rule stays
 * as-is for check-in. The tournament's own phase does not participate: an
 * `ends_at` reaching past the LIVE start keeps registration open by itself.
 *
 * `allow_late_registration` lifts `ends_at` and NOTHING else — it cannot open a
 * tournament with no row, one whose window has not started, or a finished one.
 * Keep this in lockstep with the backend predicate: this function only decides
 * whether to render the register button, and a client that disagrees with the
 * server either hides a working button or offers one that 400s.
 */
export function isRegistrationOpen(
  tournament: Pick<Tournament, "status" | "phase_schedule" | "allow_late_registration">,
  now: number = Date.now()
) {
  if (tournament.status === "completed" || tournament.status === "archived") return false;

  const row = tournament.phase_schedule?.find((entry) => entry.status === "registration");
  if (!row) return false;

  const startsAt = new Date(row.starts_at).getTime();
  if (startsAt > now) return false;

  const endsAt = row.ends_at ? new Date(row.ends_at).getTime() : null;
  return endsAt === null || tournament.allow_late_registration === true || now <= endsAt;
}

/**
 * Whether the tournament's streams belong on screen at all.
 *
 * Only while something is actually being broadcast: the live player draft, and
 * match play (`live`/`playoffs`, the two statuses that share the "live"
 * presentation bucket — checked through that bucket so a future in-progress
 * status is included by the same rule that colours it green). Earlier the dock
 * is a permanent "channel is offline" card and the Streams tab an empty list;
 * afterwards a finished event's channel is somebody else's stream.
 */
export function areStreamsVisible(status: TournamentStatus) {
  return status === "draft" || TOURNAMENT_STATUS_META[status].variant === "live";
}
