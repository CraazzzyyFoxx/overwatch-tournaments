import type { useTranslations } from "next-intl";

import { getTournamentStatusMeta } from "@/lib/tournament/status";
import type { Encounter } from "@/types/encounter.types";
import type { Tournament, TournamentStatus } from "@/types/tournament.types";

// Loose translator alias matching next-intl's `useTranslations()` return type so
// callers can hand their `t` straight through (strictFunctionTypes-safe).
type Translate = ReturnType<typeof useTranslations<never>>;

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
//
// Bucketed by the status's presentation variant rather than by listing statuses
// again: which statuses read as "signing up" is already decided once, in
// `@/lib/tournament/status`.
export function stageProgress(
  tournament: Tournament,
  status: TournamentStatus,
  t: Translate
): StageProgress {
  switch (getTournamentStatusMeta(status).variant) {
    case "finished":
      return { label: t("tournamentsList.stage.final"), pct: 100, fill: "teal" };
    case "upcoming":
      return { label: t("tournamentsList.stage.signups"), pct: 30, fill: "amber" };
    case "draft":
      return { label: t("tournamentsList.stage.setup"), pct: 20, fill: "muted" };
  }

  const stages = tournament.stages ?? [];
  const total = stages.length;
  const completed = stages.filter((stage) => stage.is_completed).length;
  const active = stages.find((stage) => stage.is_active);
  const pct = total > 0 ? Math.min(95, Math.max(10, Math.round((completed / total) * 100))) : 50;
  return { label: active?.name ?? t("common.live"), pct, fill: "teal" };
}

// Current-map name from the live encounter, if a map is in progress.
export function currentMapName(encounter: Encounter): string | null {
  const index = encounter.current_map_index;
  if (index == null) return null;
  const match = encounter.matches?.[index];
  return match?.map?.name ?? null;
}
