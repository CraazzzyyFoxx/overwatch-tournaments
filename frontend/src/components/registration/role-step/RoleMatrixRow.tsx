"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Eyebrow } from "@/components/ui/eyebrow";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { roleAccent } from "@/lib/registration/role-accent";
import {
  findRole,
  ratedDimension,
  rolePresentation,
  type RoleOntology,
} from "@/lib/roster/ontology";
import { cn } from "@/lib/utils";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { SubroleOption } from "@/types/registration.types";

import type { RoleCode, RolePriority, RoleSelection } from "../types";
import { HeroPickerCell } from "./HeroPickerCell";

/** Radix `Select` cannot carry an empty item value; `""` means "no preference". */
const ANY_SUBROLE = "__any__";

export interface RoleMatrixRowProps {
  roleCode: RoleCode;
  roleLabel: string;
  /** The owner game's scoped ontology: the glyph and accent are this role's own presentation. */
  ontology: RoleOntology | null;
  selection: RoleSelection;
  subroleOptions: readonly SubroleOption[];
  /** Characters offered for this row: the owner game's whole roster. A class is a display property, never a role. */
  heroes: CatalogEntityRead[];
  topHeroesEnabled: boolean;
  maxHeroes: number;
  /** Hidden in the forced-flex mode, where every role is main by definition. */
  showPriority?: boolean;
  /** `false` in a one-role game: the row is that role's heroes and specialization, not a role to name. */
  showRole?: boolean;
  onPriorityChange: (priority: RolePriority) => void;
  onSubroleChange: (subrole: string) => void;
  onHeroesChange: (heroes: string[]) => void;
}

export function RoleMatrixRow({
  roleCode,
  roleLabel,
  ontology,
  selection,
  subroleOptions,
  heroes,
  topHeroesEnabled,
  maxHeroes,
  showPriority = true,
  showRole = true,
  onPriorityChange,
  onSubroleChange,
  onHeroesChange,
}: Readonly<RoleMatrixRowProps>) {
  const t = useTranslations();
  const subroleId = useId();
  const rated = ontology ? ratedDimension(ontology) : null;
  const roleRef = rated ? { dimension: rated.code, role: roleCode } : null;
  const node = ontology && roleRef ? findRole(ontology, roleRef) : null;
  const color = ontology && node ? rolePresentation(ontology.roles, node.id).color : null;
  const accent = roleAccent(color);
  const active = showPriority ? selection.priority !== "off" : true;

  const priorityOptions: readonly { value: RolePriority; label: string; accent?: string }[] = [
    { value: "off", label: t("registration.roles.matrix.off") },
    { value: "fallback", label: t("registration.roles.matrix.fallback") },
    { value: "main", label: t("registration.roles.matrix.main"), accent: color ?? undefined },
  ];

  return (
    <div
      className={cn(
        "grid items-center gap-2 rounded-xl border p-2 transition-colors",
        showPriority
          ? "sm:grid-cols-[minmax(6rem,0.8fr)_minmax(0,13rem)_minmax(0,1fr)_minmax(0,8.5rem)]"
          : showRole
            ? "sm:grid-cols-[minmax(6rem,0.8fr)_minmax(0,1fr)_minmax(0,8.5rem)]"
            : "sm:grid-cols-[minmax(0,1fr)_minmax(0,8.5rem)]",
        active
          ? "border-[color:var(--aqt-border-3)] bg-[color:var(--aqt-overlay-2)]"
          : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)]",
      )}
    >
      {showRole && (
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className="flex size-7 shrink-0 items-center justify-center rounded-xl"
            style={accent.tile}
          >
            <PlayerRoleIcon role={roleRef} ontology={ontology} size={18} decorative />
          </span>
          <span
            className={cn(
              "truncate text-label font-semibold",
              active ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-muted)]",
            )}
          >
            {roleLabel}
          </span>
        </div>
      )}

      {showPriority && (
        <ToggleGroup
          variant="pill"
          size="sm"
          aria-label={t("registration.roles.matrix.priorityLabel", { role: roleLabel })}
          value={selection.priority}
          onValueChange={(priority) => onPriorityChange(priority as RolePriority)}
          className="w-full"
        >
          {priorityOptions.map((option) => (
            <ToggleGroupItem
              key={option.value}
              value={option.value}
              accent={option.accent}
              className="flex-1 whitespace-nowrap px-2"
            >
              {option.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      )}

      {/* The column headers only exist from `sm` up, so the stacked layout
          carries its own labels instead of leaving bare controls. */}
      {subroleOptions.length > 0 ? (
        <div className="grid gap-1">
          <Eyebrow tone="muted" className="sm:hidden">
            {t("registration.roles.specialization")}
          </Eyebrow>
          <Select
            value={selection.subrole || ANY_SUBROLE}
            disabled={!active}
            onValueChange={(next) => onSubroleChange(next === ANY_SUBROLE ? "" : next)}
          >
            <SelectTrigger
              id={subroleId}
              aria-label={
                showRole
                  ? t("registration.roles.roleSpecialization", { role: roleLabel })
                  : t("registration.roles.specialization")
              }
              variant="surface"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY_SUBROLE}>{t("registration.roles.any")}</SelectItem>
              {subroleOptions.map((option) => (
                <SelectItem key={option.slug} value={option.slug}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : (
        <div aria-hidden />
      )}

      {topHeroesEnabled ? (
        <div className="grid gap-1">
          <Eyebrow tone="muted" className="sm:hidden">
            {t("registration.roles.topHeroes.title")}
          </Eyebrow>
          <HeroPickerCell
            accent={accent}
            roleLabel={roleLabel}
            showRole={showRole}
            heroes={heroes}
            selected={selection.topHeroes}
            max={maxHeroes}
            disabled={!active}
            onChange={onHeroesChange}
          />
        </div>
      ) : (
        <div aria-hidden />
      )}
    </div>
  );
}
