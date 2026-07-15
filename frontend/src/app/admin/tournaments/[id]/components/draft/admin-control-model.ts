import type {
  DraftFeasibility,
  DraftPickOption,
  DraftPlayer,
  DraftPresenceState,
  DraftRole,
  DraftRoleEditResponse,
  DraftTeam
} from "@/types/draft.types";

const ROLES: DraftRole[] = ["tank", "dps", "support"];

export function availableRolesForPlayer(player: DraftPlayer): DraftRole[] {
  const declared = new Set<DraftRole>([
    player.primary_role,
    ...((player.secondary_roles_json ?? []) as DraftRole[])
  ]);
  return ROLES.filter((role) => !declared.has(role));
}

interface RoleEditCommitState {
  player: DraftPlayer | null;
  role: DraftRole | null;
  rankValue: number | null;
  rankAbsent: boolean;
  reason: string;
  preview: DraftRoleEditResponse | null;
}

export function canCommitRoleEdit(state: RoleEditCommitState): boolean {
  const { player, role, rankValue, rankAbsent, reason, preview } = state;
  if (!player || !role || !preview || !reason.trim()) return false;
  if (rankValue == null && !rankAbsent) return false;
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

export interface CaptainPresenceRow {
  teamId: number;
  teamName: string;
  connected: boolean;
  lastActiveAt: string | null;
}

export function captainPresenceRows(
  teams: DraftTeam[],
  presence: DraftPresenceState
): CaptainPresenceRow[] {
  return [...teams]
    .sort((left, right) => left.draft_position - right.draft_position)
    .map((team) => {
      const entry =
        team.captain_auth_user_id == null ? undefined : presence.users[team.captain_auth_user_id];
      return {
        teamId: team.id,
        teamName: team.name,
        connected: entry != null,
        lastActiveAt: entry?.last_active_at ?? null
      };
    });
}

export function buildOverrideRequest(
  option: Pick<DraftPickOption, "player_id" | "role">,
  expectedVersion: number,
  note: string
) {
  return {
    player_id: option.player_id,
    target_role: option.role,
    expected_version: expectedVersion,
    note: note.trim()
  };
}
