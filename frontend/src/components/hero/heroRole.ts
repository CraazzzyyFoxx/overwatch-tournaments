/** Hero/role helpers shared across the app (profile, encounters, teams, …). */

export type AqtRoleKey = "tank" | "damage" | "support";

const ROLE_NORMALIZED: Record<string, AqtRoleKey> = {
  tank: "tank",
  Tank: "tank",
  damage: "damage",
  Damage: "damage",
  dps: "damage",
  DPS: "damage",
  support: "support",
  Support: "support",
  healer: "support",
  Healer: "support"
};

export const normalizeRole = (role: string | null | undefined): AqtRoleKey | null => {
  if (!role) return null;
  return ROLE_NORMALIZED[role] ?? ROLE_NORMALIZED[role.toLowerCase()] ?? null;
};

export const heroVariantFromRole = (role: string | null | undefined): AqtRoleKey => {
  return normalizeRole(role) ?? "damage";
};

export const heroInitials = (name: string): string => {
  if (!name) return "?";
  const parts = name.replace(/[^A-Za-zА-Яа-я0-9]/g, " ").trim().split(/\s+/);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
};
