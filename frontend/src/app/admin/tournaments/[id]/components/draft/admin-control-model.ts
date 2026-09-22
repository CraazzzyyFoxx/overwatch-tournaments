import type {
  DraftFeasibility,
  DraftPlayer,
  DraftRole,
  DraftRoleEditResponse
} from "@/types/draft.types";

const ROLES: DraftRole[] = ["tank", "damage", "support"];

export function availableRolesForPlayer(player: DraftPlayer): DraftRole[] {
  const declared = new Set<DraftRole>(player.secondary_roles as DraftRole[]);
  if (player.primary_role) declared.add(player.primary_role);
  return ROLES.filter((role) => !declared.has(role));
}

interface RoleEditCommitState {
  player: DraftPlayer | null;
  role: DraftRole | null;
  rankValue: number | null;
  reason: string;
  preview: DraftRoleEditResponse | null;
}

export function canCommitRoleEdit(state: RoleEditCommitState): boolean {
  const { player, role, rankValue, reason, preview } = state;
  if (!player || !role || !preview || !reason.trim()) return false;
  // A rankless role is not playable, so the edit would add a role the draft can
  // never offer. The server requires `rank_value > 0`; there is no "no rank"
  // path to allow any more.
  if (rankValue == null || rankValue <= 0) return false;
  return (
    preview.player_id === player.id &&
    preview.player_version === player.version &&
    preview.role === role &&
    preview.after.matched_slots >= preview.before.matched_slots
  );
}

export type RoleEditImpact = "resolved" | "improved" | "unchanged" | "worse";

export function roleEditImpact(preview: {
  before: DraftFeasibility;
  after: DraftFeasibility;
}): RoleEditImpact {
  if (preview.after.is_feasible) return "resolved";
  if (preview.after.matched_slots > preview.before.matched_slots) return "improved";
  if (preview.after.matched_slots < preview.before.matched_slots) return "worse";
  return "unchanged";
}

