import { reachedAtLeast } from "@/lib/tournament/lifecycle";
import type { TournamentStatus } from "@/types/tournament.types";

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

// Colors mirror `TournamentStatusPill`'s variants (draft=blue, upcoming=amber,
// live=rose, finished=dim) so a card and the tournament page never disagree
// about what a status looks like.
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

/**
 * Whether a participant's broadcast may have been recorded, so the past
 * broadcasts are worth a read. The poller records POV sessions from check-in
 * on, and unlike live streams they stay worth showing after the event ends.
 */
export function mayHavePastBroadcasts(status: TournamentStatus) {
  return reachedAtLeast(status, "check_in");
}
