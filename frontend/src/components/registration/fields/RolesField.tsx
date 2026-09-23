"use client";

import type { FieldRendererProps } from "@/components/forms/types";
import type { RoleCode } from "@/lib/roster/roles";
import type { FormField, RolesParams } from "@/types/forms.types";
import type { RoleInput } from "@/types/registration.types";

import RoleStep from "../RoleStep";
import { createRoleSelections, fromRoleSelections, type FlexMode } from "../types";

/**
 * `roles.params` with every default filled in.
 *
 * `FormField.params` is an untyped bag on the wire, and a form written by an
 * older builder simply omits keys. Reading it through here means the matrix
 * never branches on `undefined` — the defaults mirror
 * `shared.domain.forms.builtins.RolesParams` field for field.
 */
export function rolesParams(field: FormField): RolesParams {
  const params = field.params as Partial<RolesParams>;
  const heroes = params.top_heroes;
  return {
    primary_required: params.primary_required ?? true,
    additional_required: params.additional_required ?? false,
    flex_allowed: params.flex_allowed ?? true,
    flex_mode: params.flex_mode ?? "optional",
    subroles: params.subroles ?? {},
    top_heroes: {
      enabled: heroes?.enabled ?? false,
      required: heroes?.required ?? false,
      max: heroes?.max && heroes.max > 0 ? heroes.max : 5,
    },
  };
}

/** How the tournament presents the priority choice. `flex_allowed: false` is
 *  the old `flex_role.enabled: false`, i.e. no flex on offer at all. */
export function roleFlexMode(params: RolesParams): FlexMode {
  return params.flex_allowed ? params.flex_mode : "off";
}

/**
 * The answer a fresh registration starts with.
 *
 * Load-bearing, not cosmetic: only roles that are not `off` are submitted, and
 * the modes that render no per-row priority control (`forced`, and any locked
 * slot) offer no way to lift a role off it — so an all-`off` start would submit
 * no roles at all and the server would refuse the whole form.
 */
export function defaultRoleAnswer(
  params: RolesParams,
  lockedRole: RoleCode | null = null,
): RoleInput[] {
  return fromRoleSelections(createRoleSelections(roleFlexMode(params)), lockedRole);
}

export default function RolesField({
  field,
  value,
  onChange,
  error,
  context,
}: Readonly<FieldRendererProps>) {
  const params = rolesParams(field);
  return (
    <RoleStep
      params={params}
      subroleCatalog={context.subroleCatalog}
      value={Array.isArray(value) ? (value as RoleInput[]) : []}
      onChange={onChange}
      error={error}
      allHeroes={context.heroes}
      hideHelperText={context.mode === "admin"}
      lockedRole={context.lockedRole}
    />
  );
}
