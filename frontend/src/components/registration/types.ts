import { ROLES, type RoleCode } from "@/lib/roles";
import type { RoleInput } from "@/types/registration.types";

/**
 * How willing the registrant is to play a role.
 *
 * `main` is what the backend calls `is_primary`; a submission where every role
 * is `main` is what it derives as a flex registration
 * (`_is_flex_submission`, tournament-service `validation.py`).
 */
export type RolePriority = "off" | "fallback" | "main";

export interface RoleSelection {
  priority: RolePriority;
  subrole: string;
  /** Ordered hero slugs (top picks) for this role. */
  topHeroes: string[];
}

/**
 * One entry per role, always present.
 *
 * The wizard used to model roles as `primaryRole` + `additionalRoles[]` +
 * three separate hero lists, so choosing a role had to *reveal* the controls
 * that belonged to it. A fixed per-role map makes the role step a matrix whose
 * shape never changes with the selection.
 */
export type RoleSelections = Record<RoleCode, RoleSelection>;

const EMPTY_ROLE_SELECTION: RoleSelection = {
  priority: "off",
  subrole: "",
  topHeroes: [],
};

/** How the tournament presents the flex/priority choice. */
export type FlexMode = "off" | "optional" | "all_roles" | "forced";

/**
 * One entry per role, all `off` by default.
 *
 * The starting priority is the mode's, and it is load-bearing: the wizard only
 * submits roles whose priority is not `off`.
 *
 * - `optional` — nothing selected; the registrant opts roles in.
 * - `all_roles` — every role `fallback`: all three are submitted and playable,
 *   but no priority is chosen yet. The backend rejects a submission that names
 *   neither a priority nor flex, which is exactly the state this starts in.
 * - `forced` — every role `main`, which is both the target state and the only
 *   state, since that mode renders no choice at all.
 */
export function createRoleSelections(mode: FlexMode = "optional"): RoleSelections {
  const priority: RolePriority =
    mode === "forced" ? "main" : mode === "all_roles" ? "fallback" : "off";
  return {
    tank: { ...EMPTY_ROLE_SELECTION, priority },
    damage: { ...EMPTY_ROLE_SELECTION, priority },
    support: { ...EMPTY_ROLE_SELECTION, priority },
  };
}

/**
 * The single choice an `all_roles` tournament asks for: one priority role, or
 * flex. `null` means the registrant has not chosen yet.
 */
export function priorityChoice(selections: RoleSelections): RoleCode | "flex" | null {
  const mains = (Object.keys(selections) as RoleCode[]).filter(
    (code) => selections[code].priority === "main",
  );
  if (mains.length === 0) return null;
  if (mains.length === 1) return mains[0];
  return "flex";
}

/** A flex registration is every role marked `main` — mirrors the backend rule. */
export function isFlexSelection(selections: RoleSelections): boolean {
  const active = Object.values(selections).filter((entry) => entry.priority !== "off");
  return active.length > 1 && active.every((entry) => entry.priority === "main");
}

/**
 * The stored `roles` answer → the matrix's per-role map.
 *
 * A role the answer does not name is one the registrant did not take, which is
 * `off`. The two representations are otherwise the same information: presence
 * plus `is_primary` is priority, and order is only a tiebreak the server
 * rebuilds from `is_primary`.
 */
export function toRoleSelections(value: readonly RoleInput[]): RoleSelections {
  const selections = createRoleSelections();
  for (const entry of value) {
    if (!(entry.role in selections)) continue;
    selections[entry.role as RoleCode] = {
      priority: entry.is_primary ? "main" : "fallback",
      subrole: entry.subrole ?? "",
      topHeroes: entry.top_heroes ?? [],
    };
  }
  return selections;
}

/**
 * The matrix's map → the stored `roles` answer, main role first.
 *
 * A locked slot submits exactly that role, always primary: it is the one role
 * the invite bought, and the matrix hides the control that could say otherwise.
 * Without the filter the two hidden rows would ride along whenever the form's
 * flex mode seeded them non-`off`, registering the invitee for roles the team
 * never offered.
 */
export function fromRoleSelections(
  selections: RoleSelections,
  lockedRole: RoleCode | null = null,
): RoleInput[] {
  const rows = lockedRole
    ? ROLES.filter((role) => role.code === lockedRole)
    : ROLES.filter((role) => selections[role.code].priority !== "off");
  return rows
    .sort((a, b) => {
      const rank = (code: RoleCode) => (selections[code].priority === "main" ? 0 : 1);
      return rank(a.code) - rank(b.code);
    })
    .map((role) => {
      const selection = selections[role.code];
      return {
        role: role.code,
        ...(selection.subrole ? { subrole: selection.subrole } : {}),
        is_primary: lockedRole != null || selection.priority === "main",
        ...(selection.topHeroes.length > 0 ? { top_heroes: selection.topHeroes } : {}),
      };
    });
}
