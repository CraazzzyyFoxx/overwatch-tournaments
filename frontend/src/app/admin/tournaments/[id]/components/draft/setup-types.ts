import type { RosterShape } from "@/lib/roster/shape";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { DraftAutopickStrategy, DraftCaptainOrder, DraftRole } from "@/types/draft.types";

/**
 * The roster shape and the draft format are NOT here: both belong to the
 * tournament, and the server copies them into the session it creates.
 */
export interface DraftSetupConfig {
  /** `null` = follow the most teams the pool can fill (`maxDraftTeamCount`). */
  teamCount: number | null;
  pickTimeSeconds: number;
  /** Grace period added when the main clock expires; 0 disables overtime. */
  overtimeSeconds: number;
  autopickStrategy: DraftAutopickStrategy;
  allowAdminOverride: boolean;
}

export interface DraftCaptainSetup {
  ids: number[];
  teamNames: Record<number, string>;
  /** Roles the organizer seated a captain on; absent = the captain's lead role. */
  roles: Record<number, DraftRole>;
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

export interface DraftCaptainSeat {
  /** The role the captain is seated on — `null` when no role is playable. */
  role: DraftRole | null;
  /** That role's rank; the best playable rank under a role-less shape. */
  rank: number | null;
  /** Roles the captain can be seated on: playable, and with a slot in the shape. */
  options: DraftRole[];
}

/**
 * The role a captain is seated on and what they are worth there — the client
 * twin of the server's `ranks.seat_role` / `ranks.captain_rank`, so the rank
 * shown in the captain step is the one the seat order sorts by.
 *
 * `pinned` holds while it is playable and has a slot; otherwise the lead role
 * (flagged primary, else the first by priority). A role-less shape seats
 * nobody on a role, so it answers the best playable rank and no options.
 */
export function captainSeat(
  registration: AdminRegistration,
  pinned: DraftRole | undefined,
  shape: Pick<RosterShape, "slots" | "has_role_slots">
): DraftCaptainSeat {
  const playable = (registration.roles ?? [])
    .filter((entry) => entry.is_active && entry.rank_value != null && entry.rank_value > 0)
    .sort((left, right) => left.priority - right.priority);
  if (!shape.has_role_slots) {
    const best = playable.reduce<number | null>(
      (max, entry) => (max == null || entry.rank_value! > max ? entry.rank_value! : max),
      null
    );
    return { role: null, rank: best, options: [] };
  }
  const options = playable
    .map((entry) => entry.role as DraftRole)
    .filter((role) => (shape.slots[role] ?? 0) > 0);
  const seated =
    (pinned && options.includes(pinned) && playable.find((entry) => entry.role === pinned)) ||
    playable.find((entry) => entry.is_primary) ||
    playable[0];
  return {
    role: (seated?.role as DraftRole | undefined) ?? null,
    rank: seated?.rank_value ?? null,
    options
  };
}

export function registrationLabel(registration: AdminRegistration): string {
  return registration.battle_tag || registration.display_name || `#${registration.id}`;
}
