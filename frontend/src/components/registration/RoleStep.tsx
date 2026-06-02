"use client";

import { type ReactNode } from "react";

import FlexIcon from "@/components/icons/FlexIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { cn } from "@/lib/utils";
import {
  MAIN_ROLE_LAYOUT_ORDER,
  REGISTRATION_TO_CANONICAL,
  ROLE_ACCENTS,
  ROLES,
  getRoleIconName,
  getSubroleOptions,
  type RoleCode,
} from "@/lib/roles";
import type { Hero } from "@/types/hero.types";
import type { RegistrationForm } from "@/types/registration.types";

import type { AdditionalRole } from "./types";
import { SelectionCard } from "./role-step/SelectionCard";
import { SpecializationBlock } from "./role-step/SpecializationBlock";
import { SecondaryRolesEmptyState } from "./role-step/SecondaryRolesEmptyState";
import { HeroPickerBlock } from "./role-step/HeroPickerBlock";

import { useTranslation } from "@/i18n/LanguageContext";

interface RoleStepProps {
  isFlex: boolean;
  primaryRole: string;
  subrole: string;
  additionalRoles: AdditionalRole[];
  onSetFlex: (isFlex: boolean) => void;
  onSetPrimaryRole: (role: string) => void;
  onSetSubrole: (subrole: string) => void;
  onSetAdditionalRoles: (roles: AdditionalRole[]) => void;
  primaryRoleError?: string | null;
  secondaryRolesError?: string | null;
  form: RegistrationForm;
  hideHelperText?: boolean;
  // Top-heroes picker
  allHeroes: Hero[];
  topHeroesEnabled: boolean;
  maxHeroes: number;
  flexEnabled: boolean;
  primaryRoleHeroes: string[];
  onSetPrimaryRoleHeroes: (heroes: string[]) => void;
  flexHeroes: string[];
  onSetFlexHeroes: (heroes: string[]) => void;
}

export default function RoleStep({
  isFlex,
  primaryRole,
  subrole,
  additionalRoles,
  onSetFlex,
  onSetPrimaryRole,
  onSetSubrole,
  onSetAdditionalRoles,
  primaryRoleError = null,
  secondaryRolesError = null,
  form,
  hideHelperText = false,
  allHeroes,
  topHeroesEnabled,
  maxHeroes,
  flexEnabled,
  primaryRoleHeroes,
  onSetPrimaryRoleHeroes,
  flexHeroes,
  onSetFlexHeroes,
}: RoleStepProps) {
  const { t } = useTranslation();
  const isAdditionalRolesRequired =
    form.built_in_fields?.additional_roles?.enabled !== false
    && form.built_in_fields?.additional_roles?.required === true;
  const canEditSecondaryRoles = !!primaryRole && !isFlex;
  const selectableSecondaryRoles = primaryRole ? ROLES.filter((role) => role.code !== primaryRole) : [];
  const areAllAdditionalSelected =
    canEditSecondaryRoles
    && selectableSecondaryRoles.length > 0
    && selectableSecondaryRoles.every((role) => additionalRoles.some((entry) => entry.code === role.code));
  const secondaryRolesDescription = !primaryRole
    ? t("registration.roles.secondary.descEmptyPrimary")
    : isFlex
      ? t("registration.roles.secondary.descFlex")
      : t("registration.roles.secondary.descFallback");
  const roleLayout = flexEnabled
    ? MAIN_ROLE_LAYOUT_ORDER
    : MAIN_ROLE_LAYOUT_ORDER.filter((code) => code !== "flex");
  const primaryRoleDef = ROLES.find((role) => role.code === primaryRole);

  const heroesForRole = (roleCode: string): Hero[] => {
    const canonical = REGISTRATION_TO_CANONICAL[roleCode as RoleCode];
    if (!canonical) {
      return allHeroes;
    }
    return allHeroes.filter((hero) => (hero.role || hero.type || "").toLowerCase() === canonical);
  };

  const handlePrimaryRoleSelect = (roleCode: string) => {
    if (isFlex || primaryRole !== roleCode) {
      onSetFlex(false);
      onSetPrimaryRole(roleCode);
      onSetSubrole("");
      onSetAdditionalRoles(additionalRoles.filter((entry) => entry.code !== roleCode));
    }
  };

  const handleFlexSelect = () => {
    if (!isFlex) {
      onSetFlex(true);
    }
  };

  const toggleAdditionalRole = (roleCode: string) => {
    if (!canEditSecondaryRoles || roleCode === primaryRole) {
      return;
    }

    const exists = additionalRoles.some((entry) => entry.code === roleCode);

    if (exists) {
      onSetAdditionalRoles(additionalRoles.filter((entry) => entry.code !== roleCode));
      return;
    }

    onSetAdditionalRoles([...additionalRoles, { code: roleCode, subrole: "", topHeroes: [] }]);
  };

  const setAdditionalSubrole = (roleCode: string, nextSubrole: string) => {
    if (!canEditSecondaryRoles || roleCode === primaryRole) {
      return;
    }

    const exists = additionalRoles.some((entry) => entry.code === roleCode);
    if (!exists) {
      onSetAdditionalRoles([...additionalRoles, { code: roleCode, subrole: nextSubrole, topHeroes: [] }]);
      return;
    }

    onSetAdditionalRoles(
      additionalRoles.map((entry) =>
        entry.code === roleCode ? { ...entry, subrole: nextSubrole } : entry,
      ),
    );
  };

  const setAdditionalHeroes = (roleCode: string, heroes: string[]) => {
    onSetAdditionalRoles(
      additionalRoles.map((entry) =>
        entry.code === roleCode ? { ...entry, topHeroes: heroes } : entry,
      ),
    );
  };

  const handleSelectAllAdditionalRoles = () => {
    if (!canEditSecondaryRoles) {
      return;
    }

    if (areAllAdditionalSelected) {
      onSetAdditionalRoles([]);
      return;
    }

    onSetAdditionalRoles(
      selectableSecondaryRoles.map((role) => {
        const existing = additionalRoles.find((entry) => entry.code === role.code);
        return existing ?? { code: role.code, subrole: "", topHeroes: [] };
      }),
    );
  };

  const showTopHeroes = topHeroesEnabled && (isFlex || Boolean(primaryRoleDef));

  return (
    <div className="grid gap-5">
      {!hideHelperText ? (
        <div className="space-y-1">
          <h3 className="text-xs font-medium text-white/85">{t("registration.roles.title")}</h3>
          <p className="max-w-[40rem] text-xs leading-5 text-white/42">
            {t("registration.roles.desc")}
          </p>
        </div>
      ) : null}

      <section className="space-y-2.5">
        <div className="space-y-0.5">
          <h4 className="text-xs font-medium uppercase tracking-[0.14em] text-white/55">
            {t("registration.roles.primary.title")}
          </h4>
          {!hideHelperText ? (
            <p className="text-xs leading-5 text-white/42">
              {t("registration.roles.primary.desc")}
            </p>
          ) : null}
        </div>

        {primaryRoleError && (
          <div className="rounded-lg border border-amber-400/20 bg-amber-500/[0.06] px-3 py-2 text-xs leading-5 text-amber-100/90">
            {primaryRoleError}
          </div>
        )}

        <div className="grid items-start gap-2 md:grid-cols-2">
          {roleLayout.map((roleCode) => {
            if (roleCode === "flex") {
              return (
                <SelectionCard
                  key="flex"
                  roleCode="flex"
                  label="Flex"
                  selected={isFlex}
                  reserveHintSpace
                  type="radio"
                  onClick={handleFlexSelect}
                  hint={isFlex ? t("registration.roles.flex.desc") : undefined}
                  icon={<FlexIcon width={16} height={16} />}
                />
              );
            }

            const role = ROLES.find((entry) => entry.code === roleCode);
            if (!role) {
              return null;
            }

            const selected = !isFlex && primaryRole === role.code;
            const subroles = getSubroleOptions(form, role.code).map((option) => ({
              value: option.slug,
              label: option.label,
            }));

            return (
              <SelectionCard
                key={role.code}
                roleCode={role.code}
                label={role.display}
                selected={selected}
                detailsSelectsCard={!selected}
                reserveHintSpace
                type="radio"
                onClick={() => handlePrimaryRoleSelect(role.code)}
              >
                {subroles.length > 0 && (
                  <SpecializationBlock
                    label={t("registration.roles.specialization")}
                    value={selected ? subrole : ""}
                    options={subroles}
                    disabled={!selected}
                    onDisabledSelect={(nextValue) => {
                      handlePrimaryRoleSelect(role.code);
                      onSetSubrole(nextValue);
                    }}
                    onChange={(nextValue) => onSetSubrole(nextValue)}
                  />
                )}
              </SelectionCard>
            );
          })}
        </div>
      </section>

      <section className="space-y-2.5">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2">
              <h4 className="text-xs font-medium uppercase tracking-[0.14em] text-white/55">
                {t("registration.roles.secondary.title")}
              </h4>
              <span
                className={cn(
                  "rounded-full border px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide",
                  isAdditionalRolesRequired
                    ? "border-amber-400/20 bg-amber-500/[0.08] text-amber-200/90"
                    : "border-white/10 text-white/40",
                )}
              >
                {isAdditionalRolesRequired
                  ? t("registration.roles.secondary.required")
                  : t("registration.roles.secondary.optional")}
              </span>
            </div>
            {!hideHelperText ? (
              <p className="max-w-[40rem] text-xs leading-5 text-white/42">
                {secondaryRolesDescription}
              </p>
            ) : null}
          </div>

          <button
            type="button"
            disabled={!canEditSecondaryRoles}
            onClick={handleSelectAllAdditionalRoles}
            className={cn(
              "shrink-0 rounded-lg border px-2.5 py-1 text-[11px] font-medium transition-colors",
              !canEditSecondaryRoles && "cursor-default border-white/10 bg-white/[0.02] text-white/30",
              canEditSecondaryRoles
                && (areAllAdditionalSelected
                  ? "border-violet-400/50 bg-violet-500/12 text-violet-200"
                  : "border-white/10 bg-white/[0.03] text-white/55 hover:bg-white/[0.06] hover:text-white/75"),
            )}
          >
            {areAllAdditionalSelected
              ? t("registration.roles.secondary.clearAll")
              : t("registration.roles.secondary.selectAll")}
          </button>
        </div>

        {secondaryRolesError && (
          <div className="rounded-lg border border-amber-400/20 bg-amber-500/[0.06] px-3 py-2 text-xs leading-5 text-amber-100/90">
            {secondaryRolesError}
          </div>
        )}

        {canEditSecondaryRoles ? (
          <div className="grid items-start gap-2 sm:grid-cols-2">
            {selectableSecondaryRoles.map((role) => {
              const selected = additionalRoles.some((entry) => entry.code === role.code);
              const entry = additionalRoles.find((additionalRole) => additionalRole.code === role.code);
              const subroles = getSubroleOptions(form, role.code, "additional_roles").map((option) => ({
                value: option.slug,
                label: option.label,
              }));

              return (
                <SelectionCard
                  key={role.code}
                  roleCode={role.code}
                  label={role.display}
                  selected={selected}
                  detailsSelectsCard={!selected}
                  reserveDetailsSpace={subroles.length === 0}
                  type="checkbox"
                  compact
                  onClick={() => toggleAdditionalRole(role.code)}
                >
                  {subroles.length > 0 && (
                    <SpecializationBlock
                      label={t("registration.roles.roleSpecialization", {
                        role: role.display,
                      })}
                      value={selected ? entry?.subrole ?? "" : ""}
                      options={subroles}
                      disabled={!selected}
                      onDisabledSelect={(nextValue) => setAdditionalSubrole(role.code, nextValue)}
                      onChange={(nextValue) => setAdditionalSubrole(role.code, nextValue)}
                    />
                  )}
                </SelectionCard>
              );
            })}
          </div>
        ) : (
          <SecondaryRolesEmptyState isFlex={isFlex} />
        )}
      </section>

      {showTopHeroes && (
        <section className="space-y-2.5">
          <div className="space-y-0.5">
            <h4 className="text-xs font-medium uppercase tracking-[0.14em] text-white/55">
              {t("registration.roles.topHeroes.title")}
            </h4>
            {!hideHelperText ? (
              <p className="max-w-[40rem] text-xs leading-5 text-white/42">
                {t("registration.roles.topHeroes.desc", { max: maxHeroes })}
              </p>
            ) : null}
          </div>

          {isFlex ? (
            <HeroPickerGroup
              roleCode="flex"
              label={t("registration.roles.topHeroes.anyRole")}
              icon={<FlexIcon width={14} height={14} />}
              heroes={allHeroes}
              selected={flexHeroes}
              max={maxHeroes}
              countLabel={t("registration.roles.topHeroes.count", { count: flexHeroes.length, max: maxHeroes })}
              onChange={onSetFlexHeroes}
            />
          ) : (
            <div className="space-y-2.5">
              {primaryRoleDef && (
                <HeroPickerGroup
                  roleCode={primaryRoleDef.code}
                  label={primaryRoleDef.display}
                  icon={<PlayerRoleIcon role={getRoleIconName(primaryRoleDef.code)} size={16} />}
                  heroes={heroesForRole(primaryRoleDef.code)}
                  selected={primaryRoleHeroes}
                  max={maxHeroes}
                  countLabel={t("registration.roles.topHeroes.count", {
                    count: primaryRoleHeroes.length,
                    max: maxHeroes,
                  })}
                  onChange={onSetPrimaryRoleHeroes}
                />
              )}
              {additionalRoles.map((entry) => {
                const def = ROLES.find((role) => role.code === entry.code);
                if (!def) {
                  return null;
                }
                return (
                  <HeroPickerGroup
                    key={entry.code}
                    roleCode={def.code}
                    label={def.display}
                    icon={<PlayerRoleIcon role={getRoleIconName(def.code)} size={16} />}
                    heroes={heroesForRole(def.code)}
                    selected={entry.topHeroes}
                    max={maxHeroes}
                    countLabel={t("registration.roles.topHeroes.count", {
                      count: entry.topHeroes.length,
                      max: maxHeroes,
                    })}
                    onChange={(heroes) => setAdditionalHeroes(def.code, heroes)}
                  />
                );
              })}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function HeroPickerGroup({
  roleCode,
  label,
  icon,
  heroes,
  selected,
  max,
  countLabel,
  onChange,
}: {
  roleCode: string;
  label: string;
  icon: ReactNode;
  heroes: Hero[];
  selected: string[];
  max: number;
  countLabel: string;
  onChange: (slugs: string[]) => void;
}) {
  return (
    <div className="space-y-2 rounded-xl border border-white/10 bg-white/[0.02] p-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "flex size-7 shrink-0 items-center justify-center rounded-xl",
              ROLE_ACCENTS[roleCode]?.tile,
            )}
          >
            {icon}
          </span>
          <span className="text-[12px] font-semibold text-white">{label}</span>
        </div>
        <span className="rounded-full border border-white/10 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-white/45">
          {countLabel}
        </span>
      </div>
      <HeroPickerBlock
        heroes={heroes}
        selected={selected}
        max={max}
        roleCode={roleCode}
        onChange={onChange}
      />
    </div>
  );
}
