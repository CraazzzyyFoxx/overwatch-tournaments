import { nodesOfKind } from "@/lib/tournament/flow-nodes";
import type { Tournament, TournamentDisplayStatus } from "@/types/tournament.types";

// Display text is `common.statusBadge.<status>` in the message catalogs, never here.
type TournamentStatusMeta = {
  /**
   * Which of the three presentation buckets this status falls into. The public
   * tournament surfaces collapse the display statuses into live / upcoming /
   * finished; three files each re-derived that with the same nested
   * ternary. It is a domain fact about the status, so it lives here once.
   */
  variant: "live" | "upcoming" | "finished";
  textClassName: string;
  badgeClassName: string;
  dotClassName: string;
  isActive: boolean;
  isEnded: boolean;
};

// Colors mirror `TournamentStatusPill`'s variants (upcoming=amber, live=rose, finished=dim) so a card and the tournament page never disagree
// about what a status looks like.
const TOURNAMENT_STATUS_META: Record<TournamentDisplayStatus, TournamentStatusMeta> = {
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

/**
 * The phase a surface shows (Decision 15): `registration` / `check_in` while the tournament is `live` only because a
 * registration node is open / in check-in and no stage is `live`; otherwise the tournament's status. A read without the
 * `flow_nodes` entity shows the plain status.
 */
export function displayStatus(tournament: Pick<Tournament, "status" | "flow_nodes">): TournamentDisplayStatus {
  if (tournament.status !== "live") return tournament.status;
  if ((tournament.flow_nodes ?? []).some((node) => node.kind === "stage" && node.status === "live")) return "live";
  const registrations = nodesOfKind(tournament, "registration");
  if (registrations.some((node) => node.status === "open")) return "registration";
  if (registrations.some((node) => node.status === "check_in")) return "check_in";
  return "live";
}

export function getTournamentStatusMeta(status: TournamentDisplayStatus) {
  return TOURNAMENT_STATUS_META[status];
}

export function isTournamentStatusActive(status: TournamentDisplayStatus) {
  return TOURNAMENT_STATUS_META[status].isActive;
}

export function isTournamentStatusEnded(status: TournamentDisplayStatus) {
  return TOURNAMENT_STATUS_META[status].isEnded;
}

export const TOURNAMENT_STATUS_ORDER: TournamentDisplayStatus[] = [
  "live",
  "registration",
  "check_in",
  "announcement",
  "completed",
  "archived"
];

/**
 * Whether the tournament's streams belong on screen at all.
 *
 * Only while something is actually being broadcast: the live player draft and match play, the display statuses that
 * share the "live" presentation bucket. Earlier the dock is a permanent "channel is offline" card and the Streams tab an
 * empty list; afterwards a finished event's channel is somebody else's stream.
 */
export function areStreamsVisible(status: TournamentDisplayStatus) {
  return TOURNAMENT_STATUS_META[status].variant === "live";
}

/**
 * Whether a participant's broadcast may have been recorded, so the past
 * broadcasts are worth a read. The poller records POV sessions from check-in
 * on, and unlike live streams they stay worth showing after the event ends.
 */
export function mayHavePastBroadcasts(status: TournamentDisplayStatus) {
  return reachedCheckIn(status);
}

/** Whether sign-up is behind the phase shown: check-in or anything later. */
export function reachedCheckIn(status: TournamentDisplayStatus) {
  return status !== "announcement" && status !== "registration";
}
