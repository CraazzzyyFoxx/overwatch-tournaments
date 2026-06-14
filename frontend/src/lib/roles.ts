import type {
  RegistrationForm,
  SubroleCatalog,
  SubroleOption,
} from "@/types/registration.types";

/**
 * Single source of truth for registration role codes, display labels, accent
 * colors, and sub-role resolution. Sub-role *options* are data-driven from the
 * workspace `PlayerSubRole` catalog embedded in the form payload
 * (`form.subrole_catalog`); per-tournament `built_in_fields[*].subroles` only
 * selects which catalog slugs are offered.
 */

export type RoleCode = "tank" | "dps" | "support";

export interface RoleDef {
  code: RoleCode;
  /** Short human label. */
  display: string;
  /** Icon name understood by PlayerRoleIcon. */
  icon: "Tank" | "Damage" | "Support";
}

export const ROLES: readonly RoleDef[] = [
  { code: "tank", display: "Tank", icon: "Tank" },
  { code: "dps", display: "DPS", icon: "Damage" },
  { code: "support", display: "Support", icon: "Support" },
] as const;

export const ROLE_LABELS: Record<string, string> = {
  tank: "Tank",
  dps: "DPS",
  support: "Support",
};

/** Registration role code → canonical role used by the PlayerSubRole catalog/HeroClass. */
export const REGISTRATION_TO_CANONICAL: Record<RoleCode, string> = {
  tank: "tank",
  dps: "damage",
  support: "support",
};

const CANONICAL_TO_REGISTRATION: Record<string, RoleCode> = {
  tank: "tank",
  damage: "dps",
  dps: "dps",
  support: "support",
};

/** Map a canonical catalog role (tank/damage/support) to a registration code. */
export function canonicalToRegistrationRole(role: string): RoleCode | null {
  return CANONICAL_TO_REGISTRATION[role.trim().toLowerCase()] ?? null;
}

/** Layout order for the registration role picker (Flex first). */
export const MAIN_ROLE_LAYOUT_ORDER = ["flex", "tank", "dps", "support"] as const;

export interface RoleAccent {
  tile: string;
  selectedCard: string;
  indicator: string;
  mutedIndicator: string;
}

export const ROLE_ACCENTS: Record<string, RoleAccent> = {
  tank: {
    tile: "bg-sky-500/18 text-sky-200",
    selectedCard: "border-sky-400/75 bg-sky-500/10 shadow-[0_0_0_1px_rgba(56,189,248,0.14)]",
    indicator: "border-sky-300",
    mutedIndicator: "border-sky-300/45",
  },
  dps: {
    tile: "bg-orange-500/18 text-orange-200",
    selectedCard: "border-orange-400/75 bg-orange-500/10 shadow-[0_0_0_1px_rgba(251,146,60,0.14)]",
    indicator: "border-orange-300",
    mutedIndicator: "border-orange-300/45",
  },
  support: {
    tile: "bg-emerald-500/18 text-emerald-200",
    selectedCard: "border-emerald-400/75 bg-emerald-500/10 shadow-[0_0_0_1px_rgba(52,211,153,0.14)]",
    indicator: "border-emerald-300",
    mutedIndicator: "border-emerald-300/45",
  },
  flex: {
    tile: "bg-violet-500/18 text-violet-200",
    selectedCard: "border-violet-400/75 bg-violet-500/10 shadow-[0_0_0_1px_rgba(167,139,250,0.14)]",
    indicator: "border-violet-300",
    mutedIndicator: "border-violet-300/45",
  },
};

const ROLE_ICON_NAMES: Record<string, "Tank" | "Damage" | "Support"> = {
  tank: "Tank",
  dps: "Damage",
  support: "Support",
};

export function getRoleIconName(roleCode: string): "Tank" | "Damage" | "Support" {
  return ROLE_ICON_NAMES[roleCode] ?? "Support";
}

const SUBROLE_ACRONYMS = new Set(["dps", "pov", "vk"]);

/** Humanize a sub-role slug as a fallback when no catalog label is available. */
export function formatSubroleSlug(slug: string): string {
  return slug
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => (SUBROLE_ACRONYMS.has(word) ? word.toUpperCase() : word.charAt(0).toUpperCase() + word.slice(1)))
    .join(" ");
}

/**
 * Resolve the sub-role options to offer for a role.
 *
 * - selection `undefined` (field not configured) → offer all catalog options.
 * - selection `[]` (explicit opt-out) → offer none.
 * - selection non-empty → offer the catalog options whose slug was selected.
 */
export function resolveSubroleOptions(
  catalog: SubroleCatalog | undefined,
  selection: string[] | undefined,
  role: string,
): SubroleOption[] {
  const all = catalog?.[role] ?? [];
  if (selection === undefined) {
    return all;
  }
  const enabled = new Set(selection);
  return all.filter((option) => enabled.has(option.slug));
}

/** Convenience resolver bound to a public registration form payload. */
export function getSubroleOptions(
  form: Pick<RegistrationForm, "subrole_catalog" | "built_in_fields">,
  role: string,
  fieldKey: "primary_role" | "additional_roles" = "primary_role",
): SubroleOption[] {
  return resolveSubroleOptions(
    form.subrole_catalog,
    form.built_in_fields?.[fieldKey]?.subroles?.[role],
    role,
  );
}

/** Look up a sub-role's display label from the catalog, with a humanized fallback. */
export function getSubroleLabel(
  catalog: SubroleCatalog | undefined,
  role: string,
  slug: string,
): string {
  const match = (catalog?.[role] ?? []).find((option) => option.slug === slug);
  return match?.label ?? formatSubroleSlug(slug);
}
