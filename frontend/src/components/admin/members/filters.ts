import type { FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import type { RbacRole } from "@/types/rbac.types";

/**
 * Role chips carry the ids the members endpoint takes, labelled as the cell
 * labels them. Built even while the catalogue is still loading, so `?role=` /
 * `?exclude_role=` are read on mount.
 */
export function memberFilterDefs(
  roles: readonly RbacRole[],
  labels: Readonly<{ role: string; excludeRole: string }>,
  roleLabel: (role: RbacRole) => string
): FilterDef[] {
  const options = roles.map((role) => ({ value: String(role.id), label: roleLabel(role) }));
  return [
    { key: "role", label: labels.role, kind: "single", options },
    { key: "exclude_role", label: labels.excludeRole, kind: "multi", options }
  ];
}
