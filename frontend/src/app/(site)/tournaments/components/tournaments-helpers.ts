import type { useTranslations } from "next-intl";

import type { Encounter } from "@/types/encounter.types";
import type { Tournament } from "@/types/tournament.types";
import type { TournamentStatus } from "@/types/tournament.types";

// Loose translator alias matching next-intl's `useTranslations()` return type so
// callers can hand their `t` straight through (strictFunctionTypes-safe).
type Translate = ReturnType<typeof useTranslations<never>>;

// Derive 1-2 letter initials from a team name for avatar glyphs.
export function teamInitials(name?: string | null): string {
  const cleaned = (name ?? "").trim();
  if (!cleaned) return "??";
  const words = cleaned.split(/\s+/).filter(Boolean);
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  return cleaned.slice(0, 2).toUpperCase();
}

// Compact relative time ("2m ago", "in 19d", "Mar 01") for the Updated column
// and live-card timestamps. `now` is injectable for deterministic tests.
export function relativeTime(
  value: Date | string | null | undefined,
  t: Translate,
  now: Date = new Date()
): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";

  const diffMs = now.getTime() - date.getTime();
  const past = diffMs >= 0;
  const minutes = Math.round(Math.abs(diffMs) / 60_000);

  if (minutes < 1)
    return past ? t("tournamentsList.time.justNow") : t("tournamentsList.time.soon");
  if (minutes < 60)
    return past
      ? t("tournamentsList.time.minutesAgo", { count: minutes })
      : t("tournamentsList.time.inMinutes", { count: minutes });

  const hours = Math.round(minutes / 60);
  if (hours < 24)
    return past
      ? t("tournamentsList.time.hoursAgo", { count: hours })
      : t("tournamentsList.time.inHours", { count: hours });

  const days = Math.round(hours / 24);
  if (days < 30)
    return past
      ? t("tournamentsList.time.daysAgo", { count: days })
      : t("tournamentsList.time.inDays", { count: days });

  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export interface LiveTournamentGroup {
  tournament: Tournament;
  encounters: Encounter[];
  // Headline encounter rendered in the "NOW" strip.
  current: Encounter;
}

// Group the overview's flat list of live encounters by tournament, preserving
// first-seen order so the most relevant tournament becomes the big card.
export function groupLiveByTournament(live: ReadonlyArray<Encounter>): LiveTournamentGroup[] {
  const order: number[] = [];
  const groups = new Map<number, LiveTournamentGroup>();

  for (const encounter of live) {
    const tournament = encounter.tournament;
    const key = encounter.tournament_id ?? tournament?.id;
    if (key == null || !tournament) continue;

    const existing = groups.get(key);
    if (existing) {
      existing.encounters.push(encounter);
    } else {
      groups.set(key, { tournament, encounters: [encounter], current: encounter });
      order.push(key);
    }
  }

  return order.map((key) => groups.get(key) as LiveTournamentGroup);
}

export interface StageProgress {
  label: string;
  pct: number;
  fill: "teal" | "amber" | "muted";
}

// Coarse stage-progress proxy from stage completion flags. Real "X/Y matches"
// requires a precomputed backend field (see plan C2); until then we render a
// graceful label + bar derived from stages.is_completed / is_active.
export function stageProgress(
  tournament: Tournament,
  status: TournamentStatus,
  t: Translate
): StageProgress {
  if (status === "completed" || status === "archived") {
    return { label: t("tournamentsList.stage.final"), pct: 100, fill: "teal" };
  }
  if (status === "registration" || status === "check_in") {
    return { label: t("tournamentsList.stage.signups"), pct: 30, fill: "amber" };
  }
  if (status === "draft") {
    return { label: t("tournamentsList.stage.setup"), pct: 20, fill: "muted" };
  }

  // live, playoffs
  const stages = tournament.stages ?? [];
  const total = stages.length;
  const completed = stages.filter((stage) => stage.is_completed).length;
  const active = stages.find((stage) => stage.is_active);
  const pct = total > 0 ? Math.min(95, Math.max(10, Math.round((completed / total) * 100))) : 50;
  return { label: active?.name ?? t("common.live"), pct, fill: "teal" };
}

const AVATAR_GRADIENTS = [
  "linear-gradient(135deg,hsl(174 72% 55%),hsl(174 60% 30%))",
  "linear-gradient(135deg,hsl(340 75% 65%),hsl(340 60% 38%))",
  "linear-gradient(135deg,hsl(270 70% 68%),hsl(270 55% 42%))",
  "linear-gradient(135deg,hsl(38 95% 62%),hsl(38 80% 42%))",
  "linear-gradient(135deg,hsl(210 78% 65%),hsl(210 60% 38%))",
  "linear-gradient(135deg,hsl(142 65% 55%),hsl(142 50% 32%))"
];

export function avatarGradient(seed: number): string {
  const index = Math.abs(Math.trunc(seed)) % AVATAR_GRADIENTS.length;
  return AVATAR_GRADIENTS[index];
}

// Current-map name from the live encounter, if a map is in progress.
export function currentMapName(encounter: Encounter): string | null {
  const index = encounter.current_map_index;
  if (index == null) return null;
  const match = encounter.matches?.[index];
  return match?.map?.name ?? null;
}
