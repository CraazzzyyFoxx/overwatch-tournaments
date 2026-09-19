import type {
  AdminRegistration,
  AdminRegistrationUpdateInput,
  BalancerPlayerUpdateInput
} from "@/types/balancer-admin.types";

/**
 * Editor payload -> registration patch. Pure: it is the one place that decides
 * which of the player-sheet's fields become a registration write, so the
 * balancer tool and the admin registrations table cannot disagree about it.
 */
export function buildRegistrationUpdateFromPlayerPayload(
  payload: BalancerPlayerUpdateInput,
  existingRoles?: AdminRegistration["roles"]
): AdminRegistrationUpdateInput {
  const registrationPatch: AdminRegistrationUpdateInput = {};

  if (payload.role_entries_json !== undefined) {
    const existingRolesMap = new Map(
      existingRoles?.map((role) => [role.role, role.top_heroes ?? []]) ?? []
    );
    const sortedEntries = [...(payload.role_entries_json ?? [])].sort(
      (left, right) => left.priority - right.priority
    );
    registrationPatch.roles = sortedEntries.map((entry, index) => {
      const topHeroes = existingRolesMap.get(entry.role) ?? [];
      return {
        role: entry.role,
        subrole: entry.subtype,
        priority: entry.priority,
        is_primary: payload.is_flex ? true : index === 0,
        rank_value: entry.rank_value,
        // The raw column is what a write sets: `is_active` on the entry is the
        // resolver's verdict, so sending it would echo a computed value back.
        is_active: entry.is_declared_active,
        ...(topHeroes.length > 0 ? { top_heroes: topHeroes } : {})
      };
    });
  }

  if (payload.admin_notes !== undefined) {
    registrationPatch.admin_notes = payload.admin_notes;
  }
  if (payload.registration_status != null) {
    registrationPatch.status = payload.registration_status;
  }
  if (payload.registration_balancer_status != null) {
    registrationPatch.balancer_status = payload.registration_balancer_status;
  }
  if (payload.is_in_pool === false) {
    registrationPatch.balancer_status = "excluded";
    registrationPatch.exclude_reason = "manual_exclusion";
  }
  if (payload.pin) {
    registrationPatch.pin = true;
  }
  if (payload.clear_pin) {
    registrationPatch.clear_pin = true;
  }
  return registrationPatch;
}
