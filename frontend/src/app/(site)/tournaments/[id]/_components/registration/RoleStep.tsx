"use client";

import FlexIcon from "@/components/icons/FlexIcon";
import { cn } from "@/lib/utils";
import { MAIN_ROLE_LAYOUT_ORDER, ROLES, getSubroleOptions } from "@/lib/roles";
import type { RegistrationForm } from "@/types/registration.types";

import type { AdditionalRole } from "./types";
import { SelectionCard } from "./role-step/SelectionCard";
import { SpecializationBlock } from "./role-step/SpecializationBlock";
import { SecondaryRolesEmptyState } from "./role-step/SecondaryRolesEmptyState";

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

    onSetAdditionalRoles([...additionalRoles, { code: roleCode, subrole: "" }]);
  };

  const setAdditionalSubrole = (roleCode: string, nextSubrole: string) => {
    if (!canEditSecondaryRoles || roleCode === primaryRole) {
      return;
    }

    const exists = additionalRoles.some((entry) => entry.code === roleCode);
    if (!exists) {
      onSetAdditionalRoles([...additionalRoles, { code: roleCode, subrole: nextSubrole }]);
      return;
    }

    onSetAdditionalRoles(
      additionalRoles.map((entry) =>
        entry.code === roleCode ? { ...entry, subrole: nextSubrole } : entry,
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
        return existing ?? { code: role.code, subrole: "" };
      }),
    );
  };

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
          {MAIN_ROLE_LAYOUT_ORDER.map((roleCode) => {
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
    </div>
  );
}

