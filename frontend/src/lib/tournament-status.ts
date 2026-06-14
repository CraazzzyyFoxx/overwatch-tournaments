import type { TournamentStatus } from "@/types/tournament.types";

type TournamentStatusMeta = {
  label: string;
  badgeLabel: string;
  textClassName: string;
  badgeClassName: string;
  dotClassName?: string;
  isActive: boolean;
  isEnded: boolean;
};

export const TOURNAMENT_STATUS_META: Record<TournamentStatus, TournamentStatusMeta> = {
  draft: {
    label: "Draft",
    badgeLabel: "Draft",
    textClassName: "text-amber-400",
    badgeClassName: "text-amber-400",
    dotClassName: "bg-amber-400",
    isActive: true,
    isEnded: false
  },
  registration: {
    label: "Registration",
    badgeLabel: "Registration",
    textClassName: "text-sky-400",
    badgeClassName: "text-sky-400",
    dotClassName: "bg-sky-400",
    isActive: true,
    isEnded: false
  },
  check_in: {
    label: "Check-in",
    badgeLabel: "Check-in",
    textClassName: "text-orange-400",
    badgeClassName: "text-orange-400",
    dotClassName: "bg-orange-400",
    isActive: true,
    isEnded: false
  },
  live: {
    label: "Live",
    badgeLabel: "Live",
    textClassName: "text-emerald-400",
    badgeClassName: "text-emerald-400",
    dotClassName: "bg-emerald-400",
    isActive: true,
    isEnded: false
  },
  playoffs: {
    label: "Playoffs",
    badgeLabel: "Playoffs",
    textClassName: "text-violet-400",
    badgeClassName: "text-violet-400",
    dotClassName: "bg-violet-400",
    isActive: true,
    isEnded: false
  },
  completed: {
    label: "Ended",
    badgeLabel: "Ended",
    textClassName: "text-white/60",
    badgeClassName: "text-white/45",
    isActive: false,
    isEnded: true
  },
  archived: {
    label: "Archived",
    badgeLabel: "Archived",
    textClassName: "text-zinc-500",
    badgeClassName: "text-zinc-500",
    isActive: false,
    isEnded: true
  }
};

export function getTournamentStatusMeta(status: TournamentStatus) {
  return TOURNAMENT_STATUS_META[status];
}

export const TOURNAMENT_STATUS_OPTIONS = (
  Object.entries(TOURNAMENT_STATUS_META) as Array<[TournamentStatus, TournamentStatusMeta]>
).map(([value, meta]) => ({
  value,
  label: meta.badgeLabel
}));

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
  "completed",
  "archived",
  "draft"
];

export function countByTournamentStatus(
  statuses: ReadonlyArray<TournamentStatus>
): Record<TournamentStatus, number> {
  const counts: Record<TournamentStatus, number> = {
    draft: 0,
    registration: 0,
    check_in: 0,
    live: 0,
    playoffs: 0,
    completed: 0,
    archived: 0
  };
  for (const status of statuses) {
    counts[status] += 1;
  }
  return counts;
}
