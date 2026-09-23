import type { AdminRegistration } from "@/types/balancer-admin.types";
import type {
  DraftAutopickStrategy,
  DraftCaptainOrder,
  DraftFormat,
  DraftRole
} from "@/types/draft.types";

/** The roster shape is NOT here: it belongs to the tournament, not the wizard. */
export interface DraftSetupConfig {
  teamCount: number;
  pickTimeSeconds: number;
  /** Grace period added when the main clock expires; 0 disables overtime. */
  overtimeSeconds: number;
  format: DraftFormat;
  autopickStrategy: DraftAutopickStrategy;
  allowAdminOverride: boolean;
  roundRules: string[];
}

export interface DraftCaptainSetup {
  ids: number[];
  teamNames: Record<number, string>;
  order: DraftCaptainOrder;
  randomSeed: number;
}

interface DraftRegistrationSummary {
  roles: DraftRole[];
  /** `null` when no role is playable — the seed will reject this registration. */
  rank: number | null;
}

export function isInDraftPool(registration: AdminRegistration): boolean {
  return !registration.deleted_at && !registration.balancer_status_meta.excludes_from_balancer;
}

/**
 * The registration's playable roles and the rank of its leading one, read
 * straight off the rows the server already resolved: `is_active` IS "playable"
 * and `rank_value` IS the resolved rank (roster engine,
 * `shared.services.roster`). Nothing is recomputed here — no flex mode, no max
 * across roles, no default role.
 */
export function poolRegistrationSummary(registration: AdminRegistration): DraftRegistrationSummary {
  const playable = (registration.roles ?? [])
    .filter((entry) => entry.is_active)
    .sort((left, right) => left.priority - right.priority);
  const lead = playable.find((entry) => entry.is_primary) ?? playable[0] ?? null;
  return {
    roles: Array.from(new Set(playable.map((entry) => entry.role))) as DraftRole[],
    rank: lead?.rank_value ?? null
  };
}

export interface DraftCaptainRank {
  rank: number | null;
  /** The role that rank belongs to — `null` when no role is playable. */
  role: DraftRole | null;
}

/**
 * A captain's STRONGEST playable role, not their leading one.
 *
 * `poolRegistrationSummary` reads the primary role because that is what the
 * seed and the pool checks care about. A captain is seated by strength
 * ("strongest first"), and a player whose primary role happens to be their
 * weakest ranked one would otherwise be seated as if that were their level.
 */
export function captainRankSummary(registration: AdminRegistration): DraftCaptainRank {
  const best = (registration.roles ?? [])
    .filter((entry) => entry.is_active && entry.rank_value != null)
    .sort((left, right) => right.rank_value! - left.rank_value! || left.priority - right.priority)[0];
  return { rank: best?.rank_value ?? null, role: (best?.role as DraftRole) ?? null };
}

export function registrationLabel(registration: AdminRegistration): string {
  return registration.battle_tag || registration.display_name || `#${registration.id}`;
}

