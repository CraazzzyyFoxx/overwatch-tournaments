"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Checkbox } from "@craazzzyyfoxx/admin-kit/ui/checkbox";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { useRoleName } from "@/hooks/useRoleName";
import { ratedDimension, selectableRoles, selectedRoleRefs, type RoleOntology, type RoleSelection } from "@/lib/roster/ontology";
import type { RoleRef } from "@/lib/roster/team-format";

/** Radio/checkbox semantics come from the declared dimension, not a game's role count. */
export function RoleSelector({ ontology, dimension, value, onChange, disabled = false }: Readonly<{
  ontology: RoleOntology;
  dimension: string;
  value: RoleSelection;
  onChange: (value: RoleSelection) => void;
  disabled?: boolean;
}>) {
  const id = useId();
  const t = useTranslations("common.roleOntology");
  const nameOf = useRoleName();
  const axis = ontology.dimensions.find(row => row.code === dimension && row.active);
  if (!ratedDimension(ontology) || !axis) return <p role="alert">{t("metadataError")}</p>;
  const selected = selectedRoleRefs(ontology, value, dimension);
  const single = axis.selection_mode === "single";
  const commit = (refs: RoleRef[]) => onChange({ discipline: ontology.discipline.code, workspace_id: ontology.workspace_id, refs });
  const options = selectableRoles(ontology, dimension).map(role => <Label key={role.id} className="flex items-center gap-2 font-normal">
    {single ? <RadioGroupItem value={role.code} /> : <Checkbox checked={selected.some(ref => ref.role === role.code)} onCheckedChange={checked => {
      const refs = selected.filter(ref => ref.role !== role.code);
      if (checked === true) refs.push({ dimension, role: role.code });
      commit(refs);
    }} />}
    <PlayerRoleIcon role={{ dimension, role: role.code }} ontology={ontology} size={18} decorative />{nameOf(role)}
  </Label>);
  return <fieldset disabled={disabled} className="space-y-2">
    <legend id={`${id}-legend`} className="text-sm font-medium">{axis.name}</legend>
    {single ? <>
      <RadioGroup aria-labelledby={`${id}-legend`} value={selected[0]?.role ?? ""} onValueChange={role => commit([{ dimension, role }])} disabled={disabled} className="gap-2">
        {options}
      </RadioGroup>
      <Button type="button" variant="link" size="inline" onClick={() => commit([])}>{t("clear")}</Button>
    </> : options}
  </fieldset>;
}
