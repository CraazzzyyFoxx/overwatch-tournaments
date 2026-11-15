import { useMemo } from "react";
import { useTranslations } from "next-intl";

import type { FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import type { RbacRole } from "@/types/rbac.types";

/**
 * The chips that narrow the account list. Both role chips offer the same list,
 * so "every caster who is not also an admin" is two chips rather than a search.
 */
export function useAccountFilterDefs(roles: readonly RbacRole[]): FilterDef[] {
  const t = useTranslations("adminAccess.common");
  return useMemo<FilterDef[]>(
    () => [
      {
        key: "role",
        label: t("role"),
        kind: "single",
        options: roles.map((role) => ({ value: String(role.id), label: role.name }))
      },
      {
        key: "exclude_role",
        label: t("excludeRole"),
        kind: "multi",
        options: roles.map((role) => ({ value: String(role.id), label: role.name }))
      },
      {
        key: "status",
        label: t("status"),
        kind: "single",
        options: [
          { value: "active", label: t("active") },
          { value: "inactive", label: t("inactive") }
        ]
      },
      { key: "superuser", label: t("superusersOnly"), kind: "toggle" }
    ],
    [roles, t]
  );
}
