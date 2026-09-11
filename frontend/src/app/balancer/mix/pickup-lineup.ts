import { ROLES, canonicalToRegistrationRole, type RoleCode } from "@/lib/roles";
import type {
  CustomGameOutcome,
  CustomGameParticipationEntry,
  CustomGamePlayer,
  CustomGamePlayerPatch,
  CustomGameSettings,
  MixParticipation,
  RotationRecommendation,
} from "@/services/custom-game.service";

/** What recording a match needs: the click, and which balance option it was played from. */
export type PickupRecordOutcomeInput = {
  outcome: CustomGameOutcome;
  variantIndex: number;
};

/**
 * Lineup rules for a pickup mix, kept pure so the panels stay presentational.
 *
 * Two pools exist: the workspace **player pool** (everyone the workspace knows)
 * and the mix **lineup** (who is in this mix). Membership and participation are
 * separate: `participation === "benched"` sits a player out without dropping
 * their rank override or role order, so a host can toggle a late arrival on and
 * off without rebuilding anything.
 *
 * Role vocabulary is `@/lib/roles` — the same `tank`/`dps`/`support` codes the
 * balancer and the registration form use.
 */

/** Canonical role order — the order role columns and glyph rails are read in. */
export const LINEUP_ROLES: readonly RoleCode[] = ROLES.map((role) => role.code);

export const PICKUP_STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  balanced: "Balanced",
  completed: "Completed",
  cancelled: "Cancelled",
};

/** A terminal mix is read-only server-side, so its write controls are hidden. */
export const PICKUP_TERMINAL_STATUSES: Record<string, true> = { completed: true, cancelled: true };

/**
 * The roles the balancer may use for this row, in the order the host set them.
 *
 * A stored `null` means "not configured yet", which the backend expands to
 * every role the player has a rank for — mirror that here so the UI shows the
 * same set the balance would use. Position is the balancer's priority: the
 * first role in the array is the one the solver tries to seat the player in
 * first (see `CustomGamePlayer.roles`), so this is also the only order the UI
 * ever shows or writes. Reordering happens through an explicit drag in the
 * player sheet, never by re-deriving it from a rank — a rank fix and a
 * priority choice are two different decisions a host makes at two different
 * times, and folding one into the other means neither survives a moment the
 * host isn't actively looking at this row.
 */
export function resolveRoleOrder(row: Pick<CustomGamePlayer, "roles" | "ranks">): RoleCode[] {
  if (row.roles == null) {
    return LINEUP_ROLES.filter((role) => row.ranks[role] != null);
  }
  const seen = new Set<string>();
  const out: RoleCode[] = [];
  for (const code of row.roles) {
    const role = LINEUP_ROLES.find((item) => item === code);
    if (role == null || seen.has(role)) {
      continue;
    }
    seen.add(role);
    out.push(role);
  }
  return out;
}

/**
 * Turn one role on or off within a stored priority order.
 *
 * The order *is* the balancer's priority, so a role that turns on lands at the
 * end of it rather than being resorted — the host's existing order for the
 * other roles is left exactly as they set it.
 */
export function toggleRole(order: readonly RoleCode[], role: RoleCode): RoleCode[] {
  return order.includes(role) ? order.filter((item) => item !== role) : [...order, role];
}

export type LineupIssue = "no_role" | "no_rank";

export const LINEUP_ISSUE_MESSAGES: Record<LineupIssue, string> = {
  no_role: "No roles selected — balance will reject this mix",
  no_rank: "No rank on any selected role — balance will reject this mix",
};

/**
 * What would make `balance` reject this row. An active player with no playable
 * ranked role fails the whole run server-side (`missing_ranked_role`), so it is
 * worth showing before the host presses Balance.
 */
export function getLineupIssue(row: CustomGamePlayer): LineupIssue | null {
  if (row.participation === "benched") {
    return null;
  }
  const order = resolveRoleOrder(row);
  if (order.length === 0) {
    return row.roles == null ? "no_rank" : "no_role";
  }
  return order.some((role) => row.ranks[role] != null) ? null : "no_rank";
}

/** One label rule shared by the lineup, the teams and the sheet. */
export function playerLabel(
  row: Pick<CustomGamePlayer, "display_name" | "battle_tag" | "workspace_member_id">,
): string {
  return row.display_name || row.battle_tag || `#${row.workspace_member_id}`;
}

/** Mean effective rank across the roles the player can actually be assigned. */
export function averageRank(row: Pick<CustomGamePlayer, "roles" | "ranks">): number | null {
  const values = resolveRoleOrder(row)
    .map((role) => row.ranks[role])
    .filter((value): value is number => value != null);
  if (values.length === 0) {
    return null;
  }
  return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length);
}

export type LineupSummary = {
  total: number;
  active: number;
  benched: number;
  blocking: number;
};

export function summarizeLineup(rows: CustomGamePlayer[]): LineupSummary {
  let active = 0;
  let blocking = 0;
  for (const row of rows) {
    if (row.participation !== "benched") {
      active += 1;
    }
    if (getLineupIssue(row) != null) {
      blocking += 1;
    }
  }
  return { total: rows.length, active, benched: rows.length - active, blocking };
}

/**
 * A 5v5 mix needs one tank and two of each damage/support per team, so the
 * lineup needs twice that before a balance can seat everyone. Hard-coded
 * because the pickup solver runs the same 1-2-2 shape for every mix; a
 * configurable lock would come from `settings.role_mask`, which no mix sets yet.
 */
const ROLE_DEMAND: Record<RoleCode, number> = { tank: 2, dps: 4, support: 4 };

/**
 * Seats a balance can actually fill — the sum of the demand above.
 *
 * The add-players dialog counts against this rather than against a literal 10 so
 * the "you are two over a full lobby" line and the role gauges below it can
 * never disagree about how big a lobby is.
 */
export const LOBBY_SIZE: number = Object.values(ROLE_DEMAND).reduce((sum, need) => sum + need, 0);

export type RoleSupply = {
  role: RoleCode;
  /** Active players who both selected this role and carry a rank for it. */
  supply: number;
  need: number;
  /** How many more the solver would want; 0 once the role is covered. */
  short: number;
};

/**
 * Who can actually fill each role, counted the way the solver counts.
 *
 * A selected role with no rank is not supply — the balance refuses to seat it —
 * so this deliberately does not match "how many chips are lit".
 */
export function summarizeRoleSupply(rows: CustomGamePlayer[]): RoleSupply[] {
  return LINEUP_ROLES.map((role) => {
    const supply = rows.filter(
      (row) =>
        row.participation !== "benched" &&
        resolveRoleOrder(row).includes(role) &&
        row.ranks[role] != null,
    ).length;
    const need = ROLE_DEMAND[role];
    return { role, supply, need, short: Math.max(0, need - supply) };
  });
}

/** Active players first, then the host's own ordering. */
export function sortLineup(rows: CustomGamePlayer[]): CustomGamePlayer[] {
  return [...rows].sort((a, b) => {
    const aBenched = a.participation === "benched";
    const bBenched = b.participation === "benched";
    if (aBenched !== bBenched) {
      return aBenched ? 1 : -1;
    }
    return a.sort_order - b.sort_order || a.id - b.id;
  });
}

/** One roster row `applyRotationHints` moves. */
export type RotationHintPatch = { workspaceMemberId: number; patch: CustomGamePlayerPatch };

/**
 * Where each actionable rotation verdict wants the row. `neutral` is absent on
 * purpose: it is "no opinion", not a column to move anybody into.
 */
const PARTICIPATION_BY_HINT: Record<"must_play" | "should_rest", MixParticipation> = {
  must_play: "must_play",
  should_rest: "benched",
};

/**
 * The moves that bring the lineup in line with the rotation-fairness read
 * (`mix_rotation.recommend_rotation`): whoever is owed a seat is pinned, and
 * whoever should rest is benched -- each exactly like the host's own drag into
 * that column. A row already in its hinted column, or with no actionable hint,
 * is left alone, so applying is idempotent.
 */
export function computeRotationHintPatches(
  rows: readonly CustomGamePlayer[],
  recommendations: readonly RotationRecommendation[],
): RotationHintPatch[] {
  const hintByMember = new Map(recommendations.map((rec) => [rec.workspace_member_id, rec]));
  const patches: RotationHintPatch[] = [];
  for (const row of rows) {
    const status = hintByMember.get(row.workspace_member_id)?.status;
    const wanted = status == null || status === "neutral" ? null : PARTICIPATION_BY_HINT[status];
    if (wanted == null || wanted === row.participation) {
      continue;
    }
    patches.push({ workspaceMemberId: row.workspace_member_id, patch: { participation: wanted } });
  }
  return patches;
}

/** The same moves as one whole-lineup write (`customGameService.setParticipation`). */
export function participationEntries(
  patches: readonly RotationHintPatch[],
): CustomGameParticipationEntry[] {
  return patches.flatMap((entry) =>
    entry.patch.participation == null
      ? []
      : [{ workspace_member_id: entry.workspaceMemberId, participation: entry.patch.participation }],
  );
}

/** One assigned seat in a balanced team, flattened out of the role buckets. */
export type PickupSeat = {
  uuid: string;
  name: string;
  role: RoleCode;
  rating: number | null;
  /** The solver put them off their first choice. */
  offRole: boolean;
  isFlex: boolean;
  isCaptain: boolean;
  subRole: string | null;
};

export type PickupTeam = {
  id: number;
  /** The host's override, or the computed `Team N` default. */
  name: string;
  averageRank: number | null;
  seats: PickupSeat[];
};

export type PickupVariantStats = {
  compositeScore: number | null;
  mmrStdDev: number | null;
  ratingGap: number | null;
  offRoleCount: number | null;
  benchedCount: number;
};

export type PickupVariant = {
  teams: PickupTeam[];
  stats: PickupVariantStats;
  benched: string[];
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * A host's team-name overrides re-keyed by 0-based team index -- the same
 * position `parseVariants` below assigns names by. Stored relationally
 * (`custom.set_team_names`) rather than in the solver's own result, so a rename
 * survives paging between balance options and re-running the solver.
 */
export function teamNamesByIndex(settings: CustomGameSettings | undefined): Record<number, string> {
  const out: Record<number, string> = {};
  for (const [key, value] of Object.entries(settings?.team_names ?? {})) {
    const index = Number(key);
    if (Number.isInteger(index) && index >= 0 && value.trim()) {
      out[index] = value;
    }
  }
  return out;
}

function parseSeats(roster: Record<string, unknown>): PickupSeat[] {
  const seats: PickupSeat[] = [];
  for (const [name, group] of Object.entries(roster)) {
    // The solver keys buckets by its own role vocabulary (`Tank`/`Damage`/…
    // for tournaments, `tank`/`dps`/… for pickup masks); both normalise here.
    const role = canonicalToRegistrationRole(name);
    if (role == null || !Array.isArray(group)) {
      continue;
    }
    for (const entry of group) {
      const player = asRecord(entry);
      if (player?.uuid == null) {
        continue;
      }
      const preferences = Array.isArray(player.role_preferences) ? player.role_preferences : [];
      const isFlex = player.is_flex === true;
      seats.push({
        uuid: String(player.uuid),
        name: typeof player.name === "string" ? player.name : String(player.uuid),
        role,
        rating: asNumber(player.assigned_rating),
        // A flex player is never off-role: any seat is their first choice.
        offRole: !isFlex && preferences.length > 0 && preferences[0] !== name,
        isFlex,
        isCaptain: player.is_captain === true,
        subRole: typeof player.sub_role === "string" ? player.sub_role : null,
      });
    }
  }
  // Canonical role order, so the same team reads the same way every render.
  return seats.sort((a, b) => LINEUP_ROLES.indexOf(a.role) - LINEUP_ROLES.indexOf(b.role));
}

/**
 * Every balance option the solver returned, richest-first as it stored them.
 *
 * `run_balance` wraps its output as `{variants: [...]}`, and each variant is a
 * `teams_to_json` payload. An unrecognised shape yields an empty list rather
 * than throwing, so a result written by an older solver degrades to "no teams
 * to show" instead of blanking the screen.
 */
export function parseVariants(resultJson: unknown, teamNames: Record<number, string> = {}): PickupVariant[] {
  const root = asRecord(resultJson);
  if (root == null) {
    return [];
  }
  const payloads = Array.isArray(root.variants) ? root.variants : [root];
  const out: PickupVariant[] = [];
  for (const payload of payloads) {
    const variant = asRecord(payload);
    const teams = variant == null ? null : variant.teams;
    if (!Array.isArray(teams)) {
      continue;
    }
    const statistics = asRecord(variant?.statistics) ?? {};
    const benchedRows = Array.isArray(variant?.benched_players) ? variant.benched_players : [];
    out.push({
      teams: teams
        .flatMap((entry) => {
          const team = asRecord(entry);
          const roster = asRecord(team?.roster);
          if (team == null || roster == null) {
            return [];
          }
          return [{ id: asNumber(team.id), averageRank: asNumber(team.average_mmr), seats: parseSeats(roster) }];
        })
        // Named by final render position, not the raw payload index: a
        // malformed entry dropped above must not shift every name after it.
        .map((team, index) => ({
          ...team,
          id: team.id ?? index + 1,
          name: teamNames[index] ?? `Team ${index + 1}`,
        })),
      stats: {
        compositeScore: asNumber(statistics.composite_score),
        mmrStdDev: asNumber(statistics.mmr_std_dev),
        ratingGap: asNumber(statistics.max_total_rating_gap),
        offRoleCount: asNumber(statistics.off_role_count),
        benchedCount: benchedRows.length,
      },
      benched: benchedRows.flatMap((entry) => {
        const player = asRecord(entry);
        return player?.name == null ? [] : [String(player.name)];
      }),
    });
  }
  return out;
}
