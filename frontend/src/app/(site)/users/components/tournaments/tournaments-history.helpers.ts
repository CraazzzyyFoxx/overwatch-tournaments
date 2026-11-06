import type { EncounterWithUserStats, UserTournament, UserTournamentEntry } from "@/types/user.types";
import { encounterPerspective } from "@/app/(site)/users/components/shared/encounter-perspective";

// ─── Master-detail (Event dossier) helpers ──────────────────────────────────────
// Pure, side-effect-free logic shared by the explorer container, list and
// dossier. Kept here (not in a component) so it stays unit-testable.

/** W-D-L + map tallies of one tournament. */
export interface TournamentAggregate {
  won: number;
  lost: number;
  draw: number;
  mapsWon: number;
  mapsLost: number;
}
export const tournamentAggregate = (t: UserTournament): TournamentAggregate => ({
  won: t.won ?? 0,
  lost: t.lost ?? 0,
  draw: t.draw ?? 0,
  mapsWon: t.maps_won ?? 0,
  mapsLost: t.maps_lost ?? 0
});

export type PlacementMedal = "gold" | "silver" | "bronze" | "none";
export const placementMedal = (placement: number | null | undefined): PlacementMedal => {
  if (placement === 1) return "gold";
  if (placement === 2) return "silver";
  if (placement === 3) return "bronze";
  return "none";
};

/** Map winrate as a 0–100 percentage; null when the player played no maps. */
export const mapsWinratePct = (mapsWon: number, mapsLost: number): number | null => {
  const total = mapsWon + mapsLost;
  return total > 0 ? (mapsWon / total) * 100 : null;
};

/** Winrate → design-book quality colour (≥60 good, 50–59 mid, <50 bad). */
export const winrateColor = (pct: number | null): string => {
  if (pct == null) return "var(--aqt-fg)";
  if (pct >= 60) return "var(--aqt-emerald)";
  if (pct >= 50) return "var(--aqt-amber)";
  return "var(--aqt-rose)";
};

export interface StageGroup {
  key: string;
  name: string;
  encounters: EncounterWithUserStats[];
  won: number;
  lost: number;
  drawn: number;
}

/** Group a tournament's encounters by stage (first-seen order) with a per-stage
 *  W-D-L series record from the user's perspective. */
export const groupEncountersByStage = (
  t: Pick<UserTournamentEntry, "team_id" | "encounters">,
  selfUserId: number
): StageGroup[] => {
  const order: string[] = [];
  const byKey = new Map<string, StageGroup>();
  for (const enc of t.encounters) {
    const name = enc.stage?.name ?? enc.stage_item?.name ?? enc.name ?? "—";
    const key = String(enc.stage?.id ?? name);
    let group = byKey.get(key);
    if (!group) {
      group = { key, name, encounters: [], won: 0, lost: 0, drawn: 0 };
      byKey.set(key, group);
      order.push(key);
    }
    group.encounters.push(enc);
    const result = encounterPerspective(enc, selfUserId, t.team_id).kind;
    if (result === "win") group.won += 1;
    else if (result === "loss") group.lost += 1;
    else group.drawn += 1;
  }
  return order.map((key) => byKey.get(key) as StageGroup);
};
