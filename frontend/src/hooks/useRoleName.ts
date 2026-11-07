"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";

import { findRole, ratedDimension, roleName, type RoleOntology } from "@/lib/roster/ontology";
import type { OntologyRole } from "@/types/discipline.types";

/**
 * Names an ontology role for display: the localized `common.roles.<code>` message when the bundle has one for this
 * module-declared code, else the ontology's own `name` (the same shape as `useKindLabel` for catalog kinds).
 */
export function useRoleName(): (role: Pick<OntologyRole, "code" | "name" | "workspace_id">) => string {
  const t = useTranslations("common.roles");
  return useCallback(
    (role) => roleName(role, (code) => (t.has(code as never) ? t(code as never) : null)),
    [t]
  );
}

/**
 * Names a rated-role code a read reports (`tank`): through the game's dictionary when it knows the role, else the
 * bundle's localized name, else the code itself -- never a guessed one.
 */
export function useRoleCodeName(ontology?: RoleOntology | null): (code: string) => string {
  const nameOf = useRoleName();
  return useCallback(
    (code) => {
      const rated = ontology ? ratedDimension(ontology) : null;
      const role = ontology && rated ? findRole(ontology, { dimension: rated.code, role: code }) : null;
      return nameOf(role ?? { code, name: code, workspace_id: null });
    },
    [nameOf, ontology]
  );
}
