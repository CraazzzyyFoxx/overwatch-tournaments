"use client";

import { useTranslations } from "next-intl";

import FlexIcon from "@/components/icons/FlexIcon";
import { Button } from "@/components/ui/button";
import { Eyebrow, eyebrowClass } from "@/components/ui/eyebrow";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useRoleName } from "@/hooks/useRoleName";
import { roleAccent } from "@/lib/registration/role-accent";
import { cn } from "@/lib/utils";
import { getSubroleOptions } from "@/lib/roster/roles";
import { registrationRoles, rolePresentation, showsRoles, type RoleOntology } from "@/lib/roster/ontology";
import type { RolesParams } from "@/types/forms.types";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { RoleInput, SubroleCatalog } from "@/types/registration.types";

import {
  fromRoleSelections,
  isFlexSelection,
  priorityChoice,
  toRoleSelections,
  type FlexMode,
  type RoleCode,
  type RolePriority,
  type RoleSelections,
} from "./types";
import { RoleMatrixRow } from "./role-step/RoleMatrixRow";

interface RoleStepProps {
  /** The `roles` builtin's params, defaults already filled in. */
  params: RolesParams;
  /** The workspace sub-role catalog the params select from. */
  subroleCatalog: SubroleCatalog;
  /** The stored `roles` answer. */
  value: readonly RoleInput[];
  onChange: (next: RoleInput[]) => void;
  /** Field-level role error, shown once above the matrix. */
  error?: string | null;
  hideHelperText?: boolean;
  /** The owner game's characters (`top_heroes` picks are validated against exactly these). */
  allHeroes: CatalogEntityRead[];
  /**
   * The owner game's scoped ontology. The matrix has one row per registration role of its rated dimension;
   * missing or invalid metadata renders an error and no rows — nothing is synthesized.
   */
  ontology: RoleOntology | null;
  /**
   * Restrict the matrix to ONE role, permanently `main`.
   *
   * The invitee flow needs it: an invite fixes which slot the player takes, so
   * offering the other two rows would let them submit a role the team did not
   * offer — and `normalize()`'s cross-role rebalancing (which demotes whichever
   * main the user did not just touch) is meaningless with a single row.
   *
   * Specialization and top heroes stay editable: those are the invitee's own
   * data, and only the *slot* is dictated by the invite.
   */
  lockedRole?: RoleCode | null;
}

/**
 * Role step, laid out as a fixed matrix: one row per role of the owner's game, always showing the
 * same four cells (role, priority, specialization, top heroes).
 *
 * It used to be three stacked sections — primary roles, secondary roles, top
 * heroes — where the last two only appeared once a primary role was chosen and
 * the hero section grew one full roster grid per selected role. Selecting a role
 * took the step from 17 to 69 focusable controls. Here the selection only
 * changes control *state*, never the set of rendered controls.
 */
export default function RoleStep({
  params,
  subroleCatalog,
  value,
  onChange: onValueChange,
  error = null,
  hideHelperText = false,
  allHeroes,
  ontology,
  lockedRole = null,
}: Readonly<RoleStepProps>) {
  const t = useTranslations();
  const nameOf = useRoleName();
  // One vocabulary for the matrix, the roster shortfall, the invite chips and the
  // slot picker: the game's own role names from its scoped ontology.
  const roles = registrationRoles(ontology);
  const roleCodes = roles.map((role) => role.code);
  // A one-role game keeps this step only for its top heroes (the form drops it otherwise): it names no role.
  const named = showsRoles(ontology);
  const isLocked = lockedRole != null;
  // `flex_allowed: false` is the old `flex_role.enabled: false` — no flex at all.
  const flexMode: FlexMode = params.flex_allowed ? params.flex_mode : "off";
  const topHeroesEnabled = params.top_heroes.enabled;
  const maxHeroes = params.top_heroes.max;
  // The matrix thinks in one entry per role; the answer stores only the roles
  // taken. Converting at this boundary keeps both honest — the wire shape has
  // no way to say "off", and the matrix has no way to say "absent".
  const selections = toRoleSelections(roleCodes, value);
  const onChange = (next: RoleSelections) =>
    onValueChange(fromRoleSelections(roleCodes, next, lockedRole));
  const isForced = flexMode === "forced";
  const isAllRoles = !isLocked && flexMode === "all_roles";
  // A single row has nothing to prioritise against, so the control would only
  // offer the invitee a way to mark their own dictated slot as "off".
  const showPriority = !isLocked && !isForced && !isAllRoles;
  const isFlex = !isLocked && (isForced || isFlexSelection(selections));
  const visibleRoles = isLocked ? roles.filter((role) => role.code === lockedRole) : roles;
  const isAdditionalRolesRequired = params.additional_required;

  // The allowlist no longer splits by priority: one `subroles` map per role,
  // whatever slot it is taken in.
  const subroleOptionsFor = (roleCode: string) =>
    getSubroleOptions(subroleCatalog, params.subroles, roleCode);

  /**
   * Exactly one role may be `main`, unless every role is (which is how the
   * backend derives a flex registration). Anything in between is normalized by
   * demoting the mains the registrant did not just touch.
   *
   * All three mains survive in every mode that permits flex, not just
   * `optional`: `all_roles` expresses flex the same way, and since
   * `setSubrole`/`setHeroes` route through here, trimming it would turn picking
   * a specialization into "that role is now my main".
   *
   * In the forced mode three mains ARE the target state, so this is the
   * identity. Combined with the absent priority control that makes `off`
   * unreachable: `setSubrole`/`setHeroes` only ever promote.
   */
  const normalize = (next: RoleSelections, changed: RoleCode): RoleSelections => {
    if (isForced || isLocked) {
      // Locked: the one visible row is the invite's slot and stays `main`. The
      // rebalancing below would read the two hidden rows and demote it.
      return next;
    }
    const mains = roles.filter((role) => next[role.code].priority === "main");
    if (mains.length <= 1 || (mains.length === roles.length && flexMode !== "off")) {
      return next;
    }
    // A promotion names its own winner. A demotion does not: crowning a survivor
    // hands the registrant a main role they never picked, so leaving flex leaves
    // the step with no main at all and the validation asks for one.
    const keep: RoleCode | null = next[changed].priority === "main" ? changed : null;
    for (const role of mains) {
      if (role.code !== keep) {
        next[role.code] = { ...next[role.code], priority: "fallback" };
      }
    }
    return next;
  };

  const setPriority = (roleCode: RoleCode, priority: RolePriority) => {
    // No subrole reset here any more: the allowlist is one map per role, so a
    // specialization stays valid whichever slot the role is taken in.
    onChange(
      normalize({ ...selections, [roleCode]: { ...selections[roleCode], priority } }, roleCode),
    );
  };

  const setSubrole = (roleCode: RoleCode, subrole: string) => {
    // Only reachable in the priority-less modes (forced/all_roles/locked): where
    // the priority control is shown, an "off" row's cells are disabled. There a
    // specialization on an "off" role is a clear intent to play it, so promote.
    const priority = selections[roleCode].priority === "off" ? "fallback" : selections[roleCode].priority;
    onChange(
      normalize({ ...selections, [roleCode]: { ...selections[roleCode], subrole, priority } }, roleCode),
    );
  };

  const setHeroes = (roleCode: RoleCode, topHeroes: string[]) => {
    const priority =
      selections[roleCode].priority === "off" && topHeroes.length > 0
        ? "fallback"
        : selections[roleCode].priority;
    onChange(
      normalize({ ...selections, [roleCode]: { ...selections[roleCode], topHeroes, priority } }, roleCode),
    );
  };

  const toggleFlex = () => {
    const next = { ...selections };
    if (isFlex) {
      const [first, ...rest] = roles;
      next[first.code] = { ...next[first.code], priority: "main" };
      for (const role of rest) {
        next[role.code] = { ...next[role.code], priority: "fallback" };
      }
    } else {
      for (const role of roles) {
        next[role.code] = { ...next[role.code], priority: "main" };
      }
    }
    onChange(next);
  };

  /**
   * The `all_roles` choice: one priority role, or flex. Every role stays
   * playable either way — only comfort changes, so the non-chosen roles become
   * `fallback` rather than `off`.
   */
  const setPriorityChoice = (choice: RoleCode | "flex") => {
    const next = { ...selections };
    for (const role of roles) {
      next[role.code] = {
        ...next[role.code],
        priority: choice === "flex" || role.code === choice ? "main" : "fallback",
      };
    }
    onChange(next);
  };

  const columnClass = showPriority
    ? "sm:grid-cols-[minmax(6rem,0.8fr)_minmax(0,13rem)_minmax(0,1fr)_minmax(0,8.5rem)]"
    : "sm:grid-cols-[minmax(6rem,0.8fr)_minmax(0,1fr)_minmax(0,8.5rem)]";

  if (roles.length === 0) {
    // Missing, still-loading-failed or invalid (no unique rated dimension) metadata: no rows are
    // guessed, so there is nothing to answer here.
    return (
      <p role="alert" className="text-sm text-destructive">
        {t("common.roleOntology.metadataError")}
      </p>
    );
  }

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {hideHelperText || !named ? (
          <span />
        ) : (
          <p className="max-w-[38rem] text-xs leading-5 text-[color:var(--aqt-fg-muted)]">
            {isForced
              ? t("registration.roles.matrix.hintForced")
              : isAllRoles
                ? t("registration.roles.matrix.hintAllRoles")
                : isAdditionalRolesRequired
                  ? t("registration.roles.matrix.hintRequired")
                  : t("registration.roles.matrix.hint")}
          </p>
        )}

        {!isLocked && named && flexMode === "optional" && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-pressed={isFlex}
            onClick={toggleFlex}
            className="shrink-0"
            style={isFlex ? roleAccent(null).selectedCard : undefined}
          >
            <FlexIcon width={14} height={14} />
            {t("registration.roles.matrix.flexPreset")}
          </Button>
        )}
      </div>

      {error && (
        <p className="rounded-lg border border-warning/25 bg-warning/10 px-3 py-2 text-xs leading-5 text-warning">
          {error}
        </p>
      )}

      {isAllRoles && (
        <div className="grid gap-1.5">
          <Eyebrow tone="muted">{t("registration.roles.matrix.choiceLabel")}</Eyebrow>
          <ToggleGroup
            variant="pill"
            size="sm"
            aria-label={t("registration.roles.matrix.choiceLabel")}
            value={priorityChoice(selections) ?? ""}
            onValueChange={(choice) => setPriorityChoice(choice as RoleCode | "flex")}
            className="w-full"
          >
            {roles.map((role) => (
              <ToggleGroupItem
                key={role.code}
                value={role.code}
                accent={ontology ? (rolePresentation(ontology.roles, role.id).color ?? undefined) : undefined}
                className="flex-1 whitespace-nowrap px-2"
              >
                {nameOf(role)}
              </ToggleGroupItem>
            ))}
            <ToggleGroupItem value="flex" className="flex-1 whitespace-nowrap px-2">
              {t("registration.roles.matrix.choiceFlex")}
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
      )}

      {named && (
        <div
          aria-hidden
          className={cn(eyebrowClass("muted"), "hidden gap-2 px-2 sm:grid", columnClass)}
        >
          <span>{t("registration.roles.matrix.columnRole")}</span>
          {showPriority && <span>{t("registration.roles.matrix.columnPriority")}</span>}
          <span>{t("registration.roles.specialization")}</span>
          <span>{topHeroesEnabled ? t("registration.roles.topHeroes.title") : ""}</span>
        </div>
      )}

      <div className="grid gap-2">
        {visibleRoles.map((role) => (
          <RoleMatrixRow
            key={role.code}
            roleCode={role.code}
            roleLabel={nameOf(role)}
            ontology={ontology}
            selection={selections[role.code]}
            subroleOptions={subroleOptionsFor(role.code)}
            heroes={allHeroes}
            topHeroesEnabled={topHeroesEnabled}
            maxHeroes={maxHeroes}
            showPriority={showPriority}
            showRole={named}
            onPriorityChange={(priority) => setPriority(role.code, priority)}
            onSubroleChange={(subrole) => setSubrole(role.code, subrole)}
            onHeroesChange={(heroes) => setHeroes(role.code, heroes)}
          />
        ))}
      </div>
    </div>
  );
}
