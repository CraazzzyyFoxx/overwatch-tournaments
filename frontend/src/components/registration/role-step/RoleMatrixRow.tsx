"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ROLE_ACCENTS, getRoleIconName, type RoleCode } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { Hero } from "@/types/hero.types";
import type { SubroleOption } from "@/types/registration.types";

import type { RolePriority, RoleSelection } from "../types";
import { HeroPickerCell } from "./HeroPickerCell";
import { SegmentedRadio, type SegmentedOption } from "./SegmentedRadio";

/** Radix `Select` cannot carry an empty item value; `""` means "no preference". */
const ANY_SUBROLE = "__any__";

export interface RoleMatrixRowProps {
  roleCode: RoleCode;
  roleLabel: string;
  selection: RoleSelection;
  subroleOptions: readonly SubroleOption[];
  /** Heroes offered for this row — always filtered to the role's own class. */
  heroes: Hero[];
  topHeroesEnabled: boolean;
  maxHeroes: number;
  /** Hidden in the forced-flex mode, where every role is main by definition. */
  showPriority?: boolean;
  onPriorityChange: (priority: RolePriority) => void;
  onSubroleChange: (subrole: string) => void;
  onHeroesChange: (heroes: string[]) => void;
}

export function RoleMatrixRow({
  roleCode,
  roleLabel,
  selection,
  subroleOptions,
  heroes,
  topHeroesEnabled,
  maxHeroes,
  showPriority = true,
  onPriorityChange,
  onSubroleChange,
  onHeroesChange,
}: Readonly<RoleMatrixRowProps>) {
  const t = useTranslations();
  const subroleId = useId();
  const accent = ROLE_ACCENTS[roleCode] ?? ROLE_ACCENTS.flex;
  const active = showPriority ? selection.priority !== "off" : true;

  const priorityOptions: readonly SegmentedOption<RolePriority>[] = [
    { value: "off", label: t("registration.roles.matrix.off") },
    { value: "fallback", label: t("registration.roles.matrix.fallback") },
    { value: "main", label: t("registration.roles.matrix.main"), selectedClassName: accent.tile },
  ];

  return (
    <div
      className={cn(
        "grid items-center gap-2 rounded-xl border p-2 transition-colors",
        showPriority
          ? "sm:grid-cols-[minmax(6rem,0.8fr)_minmax(0,13rem)_minmax(0,1fr)_minmax(0,8.5rem)]"
          : "sm:grid-cols-[minmax(6rem,0.8fr)_minmax(0,1fr)_minmax(0,8.5rem)]",
        active
          ? "border-[color:var(--aqt-border-3)] bg-[color:var(--aqt-overlay-2)]"
          : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)]",
      )}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <span
          className={cn("flex size-7 shrink-0 items-center justify-center rounded-xl", accent.tile)}
        >
          <PlayerRoleIcon role={getRoleIconName(roleCode)} size={18} decorative />
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

      {showPriority && (
        <SegmentedRadio
          label={t("registration.roles.matrix.priorityLabel", { role: roleLabel })}
          value={selection.priority}
          options={priorityOptions}
          onChange={onPriorityChange}
        />
      )}

      {/* The column headers only exist from `sm` up, so the stacked layout
          carries its own labels instead of leaving bare controls. */}
      {subroleOptions.length > 0 ? (
        <div className="grid gap-1">
          <span className="text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-muted)] sm:hidden">
            {t("registration.roles.specialization")}
          </span>
          <Select
            value={selection.subrole || ANY_SUBROLE}
            onValueChange={(next) => onSubroleChange(next === ANY_SUBROLE ? "" : next)}
          >
            <SelectTrigger
              id={subroleId}
              aria-label={t("registration.roles.roleSpecialization", { role: roleLabel })}
              className="h-9 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] text-label text-[color:var(--aqt-fg)]"
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
          <span className="text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-muted)] sm:hidden">
            {t("registration.roles.topHeroes.title")}
          </span>
          <HeroPickerCell
            roleCode={roleCode}
            roleLabel={roleLabel}
            heroes={heroes}
            selected={selection.topHeroes}
            max={maxHeroes}
            onChange={onHeroesChange}
          />
        </div>
      ) : (
        <div aria-hidden />
      )}
    </div>
  );
}
