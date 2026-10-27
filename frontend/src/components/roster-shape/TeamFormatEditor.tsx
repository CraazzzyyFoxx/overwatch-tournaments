"use client";

import { useId, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, X } from "lucide-react";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { Button } from "@/components/ui/button";
import { triggerChevronClass } from "@/components/ui/chevron";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useRoleName } from "@/hooks/useRoleName";
import { findRole, ratedDimension, selectableRoles, type RoleOntology } from "@/lib/roster/ontology";
import { teamFormatPayload, type TeamFormatDimension, type TeamFormatRule, type TeamFormatWrite } from "@/lib/roster/team-format";
import { cn } from "@/lib/utils";

const MODES = ["off", "informational", "preference", "enforced"] as const;
const HEAD = "h-8 px-0 pr-3";
const CELL = "px-0 py-2 pr-3";
const ROW = "border-border/60 hover:bg-transparent";

/** Edits the native P2 format. No slot-map projection is ever used as an editable source. */
export function TeamFormatEditor({ value, ontology, presets, onChange, disabled = false, locked = false, showSubstitutes = false }: Readonly<{
  value: TeamFormatWrite;
  ontology: RoleOntology;
  presets: readonly TeamFormatWrite[];
  onChange: (value: TeamFormatWrite) => void;
  disabled?: boolean;
  locked?: boolean;
  /** Substitutes exist only where captains register a roster; elsewhere the bounds stay stored but hidden. */
  showSubstitutes?: boolean;
}>) {
  const id = useId();
  const t = useTranslations("common.roleOntology");
  const nameOf = useRoleName();
  const rated = ratedDimension(ontology);
  if (!rated) return <p role="alert">{t("metadataError")}</p>;
  const patch = (next: Partial<TeamFormatWrite>) => onChange({ ...value, ...next });
  // Empty is "unspecified" and zero an explicit bound, so a nullable bound says "any" when empty.
  const bound = (label: string, current: number | null | undefined, update: (next: number | null) => void, { min = 0, nullable = true, inputId }: { min?: number; nullable?: boolean; inputId?: string } = {}) => (
    <NumberInput id={inputId} integer min={min} size="sm" className="w-20" aria-label={label}
      placeholder={nullable ? t("any") : undefined} value={current} onValueChange={update} />
  );
  const range = (low: ReactNode, high: ReactNode) => (
    <div className="flex items-center gap-1.5">{low}<span aria-hidden className="text-muted-foreground">–</span>{high}</div>
  );
  const updateDimension = (dimension: string, next: Partial<TeamFormatDimension>) => {
    const exists = value.dimensions.some(entry => entry.dimension === dimension);
    patch({ dimensions: exists ? value.dimensions.map(entry => entry.dimension === dimension ? { ...entry, ...next } : entry)
      : [...value.dimensions, { dimension, mode: "off", ...next }] });
  };
  const updateRule = (index: number, next: Partial<TeamFormatRule>) => patch({ rules: value.rules.map((rule, i) => i === index ? { ...rule, ...next } : rule) });

  return <fieldset disabled={disabled || locked} className="flex min-w-0 flex-col gap-4">
    {locked && <p role="status" className="text-sm text-muted-foreground">{t("locked")}</p>}
    <SettingGroup id="format" title={t("formatTitle")}>
      {presets.length > 0 && <SettingRow htmlFor={`${id}-preset`} label={t("preset")} hint={t("presetHint")}>
        <Select value="" onValueChange={next => {
          const preset = presets[Number(next)];
          if (preset) onChange(teamFormatPayload(preset));
        }}>
          <SelectTrigger id={`${id}-preset`} size="sm" className="w-fit min-w-48 max-w-full" aria-label={t("preset")}>
            <SelectValue placeholder={t("choosePreset")} />
          </SelectTrigger>
          <SelectContent>
            {presets.map((preset, index) => <SelectItem key={preset.preset_code ?? index} value={String(index)}>{preset.name}</SelectItem>)}
          </SelectContent>
        </Select>
      </SettingRow>}
      <SettingRow htmlFor={`${id}-name`} label={t("formatName")} stacked>
        <Input id={`${id}-name`} value={value.name} maxLength={128} onChange={event => patch({ name: event.target.value })} />
      </SettingRow>
      <SettingRow htmlFor={`${id}-starters`} label={t("starters")}>
        {range(
          bound(t("starterMin"), value.starter_min, next => patch({ starter_min: next ?? 0 }), { min: 1, nullable: false, inputId: `${id}-starters` }),
          bound(t("starterMax"), value.starter_max, next => patch({ starter_max: next ?? 0 }), { min: 1, nullable: false })
        )}
      </SettingRow>
      {showSubstitutes && <SettingRow htmlFor={`${id}-substitutes`} label={t("substitutes")}>
        {range(
          bound(t("substituteMin"), value.substitute_min ?? 0, next => patch({ substitute_min: next ?? 0 }), { nullable: false, inputId: `${id}-substitutes` }),
          bound(t("substituteMax"), value.substitute_max ?? 0, next => patch({ substitute_max: next ?? 0 }), { nullable: false })
        )}
      </SettingRow>}
    </SettingGroup>

    {ontology.dimensions.map(dimension => {
      const entry = value.dimensions.find(row => row.dimension === dimension.code);
      const mode = entry?.mode ?? "off";
      const rules = value.rules.flatMap((rule, index) => {
        if (rule.role.dimension !== dimension.code) return [];
        const role = findRole(ontology, rule.role);
        // The descendants switch is a choice only for a role that has sub-roles in this workspace.
        const subRoles = role !== null && ontology.roles.some(child => child.parent_id === role.id &&
          (child.workspace_id === null || child.workspace_id === ontology.workspace_id));
        return [{ rule, index, name: role ? nameOf(role) : rule.role.role, subRoles }];
      });
      const withSubRoles = rules.some(row => row.subRoles);
      const addable = selectableRoles(ontology, dimension.code).filter(role => !rules.some(row => row.rule.role.role === role.code));
      const modeId = `${id}-${dimension.code}-mode`;
      const assignmentsId = `${id}-${dimension.code}-assignments`;
      return <fieldset key={dimension.code} disabled={!dimension.active} className="min-w-0">
        <SettingGroup id={`roles-${dimension.code}`} title={dimension.name}>
          <SettingRow htmlFor={modeId} label={t("mode")} hint={dimension.code === rated.code ? t("modeHint") : undefined}>
            <Select value={mode} onValueChange={next => updateDimension(dimension.code, { mode: next as TeamFormatDimension["mode"] })}>
              <SelectTrigger id={modeId} size="sm" className="w-fit min-w-40 max-w-full" aria-label={`${t("mode")}: ${dimension.name}`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MODES.map(option => <SelectItem key={option} value={option}>{t(option)}</SelectItem>)}
              </SelectContent>
            </Select>
          </SettingRow>
          {/* Off ignores the dimension entirely; its quotas stay stored and come back with the mode. */}
          {mode !== "off" && <div className="py-3 last:pb-0">
            {rules.length > 0 && <Table>
              <TableHeader>
                <TableRow className={ROW}>
                  <TableHead className={HEAD}>{t("roleColumn")}</TableHead>
                  <TableHead className={HEAD}>{t("required")}</TableHead>
                  <TableHead className={HEAD}>{t("recommended")}</TableHead>
                  {withSubRoles && <TableHead className={HEAD}>{t("includeDescendants")}</TableHead>}
                  <TableHead className="h-8 px-0"><span className="sr-only">{t("removeRule")}</span></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rules.map(({ rule, index, name, subRoles }) => <TableRow key={rule.role.role} className={ROW}>
                  <TableCell className={CELL}>
                    <span className="flex items-center gap-2 font-medium text-foreground">
                      <PlayerRoleIcon role={rule.role} ontology={ontology} size={18} decorative />{name}
                    </span>
                  </TableCell>
                  <TableCell className={CELL}>{range(
                    bound(`${t("hardMin")}: ${name}`, rule.hard_min, next => updateRule(index, { hard_min: next })),
                    bound(`${t("hardMax")}: ${name}`, rule.hard_max, next => updateRule(index, { hard_max: next }))
                  )}</TableCell>
                  <TableCell className={CELL}>{range(
                    bound(`${t("recommendedMin")}: ${name}`, rule.recommended_min, next => updateRule(index, { recommended_min: next })),
                    bound(`${t("recommendedMax")}: ${name}`, rule.recommended_max, next => updateRule(index, { recommended_max: next }))
                  )}</TableCell>
                  {withSubRoles && <TableCell className={CELL}>
                    {subRoles && <Checkbox aria-label={`${t("includeDescendants")}: ${name}`} checked={rule.include_descendants ?? true}
                      onCheckedChange={next => updateRule(index, { include_descendants: next === true })} />}
                  </TableCell>}
                  <TableCell className="px-0 py-2 text-right">
                    <Button type="button" variant="ghost" size="icon" aria-label={`${t("removeRule")}: ${name}`} title={t("removeRule")}
                      onClick={() => patch({ rules: value.rules.filter((_, i) => i !== index) })}>
                      <X aria-hidden className="size-4" />
                    </Button>
                  </TableCell>
                </TableRow>)}
              </TableBody>
            </Table>}
            {addable.length > 0 && <Select value="" onValueChange={code => patch({ rules: [...value.rules, { role: { dimension: dimension.code, role: code } }] })}>
              <SelectTrigger size="sm" className={cn("w-fit min-w-40 max-w-full", rules.length > 0 && "mt-2")} aria-label={`${t("addRule")}: ${dimension.name}`}>
                <SelectValue placeholder={t("addRule")} />
              </SelectTrigger>
              <SelectContent>
                {addable.map(role => <SelectItem key={role.id} value={role.code}>{nameOf(role)}</SelectItem>)}
              </SelectContent>
            </Select>}
          </div>}
          {mode !== "off" && <Collapsible className="py-3 last:pb-0"
            defaultOpen={entry?.player_min_assignments != null || entry?.player_max_assignments != null}>
            <CollapsibleTrigger asChild>
              <Button type="button" variant="ghost" size="sm" className="group/trigger -ml-3">
                <ChevronDown aria-hidden className={triggerChevronClass} />{t("advanced")}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-2">
              <SettingRow htmlFor={assignmentsId} label={t("assignments")}>
                {range(
                  bound(`${t("assignmentMin")}: ${dimension.name}`, entry?.player_min_assignments, next => updateDimension(dimension.code, { player_min_assignments: next }), { inputId: assignmentsId }),
                  bound(`${t("assignmentMax")}: ${dimension.name}`, entry?.player_max_assignments, next => updateDimension(dimension.code, { player_max_assignments: next }))
                )}
              </SettingRow>
            </CollapsibleContent>
          </Collapsible>}
        </SettingGroup>
      </fieldset>;
    })}
    {value.dimensions.filter(entry => !ontology.dimensions.some(d => d.code === entry.dimension)).map(entry =>
      <p key={entry.dimension} role="alert" className="text-sm text-destructive">{t("unknown", { role: entry.dimension })}</p>)}
  </fieldset>;
}
