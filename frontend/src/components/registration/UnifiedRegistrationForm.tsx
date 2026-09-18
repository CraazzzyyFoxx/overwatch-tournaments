"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import heroService from "@/services/hero.service";
import registrationService from "@/services/registration.service";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { useTranslations } from "next-intl";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import type {
  RegistrationForm,
  RoleInput,
} from "@/types/registration.types";
import type { RoleSelections } from "./types";
import { createRoleSelections, isFlexSelection, type FlexMode } from "./types";
import type { User } from "@/types/user.types";
import type { AdminRegistration } from "@/types/balancer-admin.types";

import { AuthUserSearchCombobox, type AuthUserOption } from "@/components/admin/AuthUserSearchCombobox";
import { rbacService } from "@/services/rbac.service";
import StepIndicator from "@/components/registration/StepIndicator";
import AccountStep from "@/components/registration/AccountStep";
import RoleStep from "@/components/registration/RoleStep";
import DetailsStep from "@/components/registration/DetailsStep";
import { ROLES, type RoleCode } from "@/lib/roles";
import {
  getFirstLiveValidationError,
  getBuiltInFieldValidationError,
  getBuiltInListValidationError,
  getCustomFieldValidationError,
  getVerifiedFieldError,
} from "@/components/registration/validation";

type StepKey = "accounts" | "roles" | "details";

interface UnifiedFormState {
  step: number;
  displayName: string;
  battleTag: string;
  smurfTags: string[];
  discordNick: string;
  twitchNick: string;
  boostyNick: string;
  notes: string;
  adminNotes: string;
  streamPov: boolean;
  status: string;
  balancerStatus: string;
  /** One entry per role — see `./types`. Replaces the old primary/additional split. */
  roleSelections: RoleSelections;
  // rank values map by role
  ranks: Record<string, string>;
  // Custom fields
  customFieldsValues: Record<string, string>;
}

type UnifiedFormAction =
  | { type: "SET_STEP"; step: number }
  | { type: "SET_FIELD"; key: keyof UnifiedFormState; value: unknown }
  | { type: "SET_RANK"; role: string; value: string }
  | { type: "SET_CUSTOM_FIELD"; key: string; value: string }
  | { type: "SET_ROLES"; selections: RoleSelections }
  | { type: "INIT_VALUES"; values: Partial<UnifiedFormState> };

const initialState: UnifiedFormState = {
  step: 0,
  displayName: "",
  battleTag: "",
  smurfTags: [],
  discordNick: "",
  twitchNick: "",
  boostyNick: "",
  notes: "",
  adminNotes: "",
  streamPov: false,
  status: "approved",
  balancerStatus: "not_in_balancer",
  roleSelections: createRoleSelections(),
  ranks: { tank: "", damage: "", support: "" },
  customFieldsValues: {},
};

function formReducer(state: UnifiedFormState, action: UnifiedFormAction): UnifiedFormState {
  switch (action.type) {
    case "SET_STEP":
      return { ...state, step: action.step };
    case "SET_FIELD":
      return { ...state, [action.key]: action.value };
    case "SET_RANK":
      return { ...state, ranks: { ...state.ranks, [action.role]: action.value } };
    case "SET_CUSTOM_FIELD":
      return {
        ...state,
        customFieldsValues: { ...state.customFieldsValues, [action.key]: action.value },
      };
    case "SET_ROLES":
      return { ...state, roleSelections: action.selections };
    case "INIT_VALUES":
      return { ...state, ...action.values };
    default:
      return state;
  }
}

interface UnifiedRegistrationFormProps {
  mode: "public" | "admin";
  tournamentId: number;
  workspaceId: number;
  formConfig: RegistrationForm;
  tournamentName?: string;
  initialData?: Partial<AdminRegistration>; // Preset values for editing (admin)
  userProfile?: User; // Suggested accounts (public)
  onSubmit: (payload: any) => Promise<void>;
  onCancel: () => void;
  submitPending?: boolean;
  /**
   * Fix the role/slot this registration takes, hiding the other matrix rows.
   *
   * Used by the team-registration flows: an invite dictates the slot, and a
   * captain picks theirs in the team section above. `null` is the ordinary
   * free-choice behaviour.
   */
  lockedRole?: RoleCode | null;
  /**
   * Suppress the form's own `<h2>`.
   *
   * For a host that already names itself visibly — the team-registration dialog
   * does — the inner title is a near-duplicate heading, and because it sits below
   * the host's own team section it makes an `<h3>` precede an `<h2>` in the
   * outline. The solo path keeps it: there the dialog title is `sr-only` and this
   * is the only visible heading.
   */
  hideTitle?: boolean;
}

export default function UnifiedRegistrationForm({
  mode,
  tournamentId,
  formConfig,
  tournamentName,
  initialData,
  userProfile,
  onSubmit,
  onCancel,
  submitPending = false,
  lockedRole = null,
  hideTitle = false,
}: Readonly<UnifiedRegistrationFormProps>) {
  const t = useTranslations();
  const openAccountSettings = useAccountSettingsModalStore((s) => s.open);
  // The mode has to be the reducer's INITIAL state, not something applied later:
  // `buildRolesPayload` only submits roles whose priority is not `off`, and the
  // modes that render no per-row priority control could never lift a role off it,
  // so an all-`off` start would submit no roles at all.
  const flexRoleConfig = formConfig.built_in_fields?.flex_role;
  const flexMode: FlexMode =
    flexRoleConfig?.enabled === false
      ? "off"
      : flexRoleConfig?.mode === "forced"
        ? "forced"
        : flexRoleConfig?.mode === "all_roles"
          ? "all_roles"
          : "optional";
  const [state, dispatch] = useReducer(formReducer, flexMode, (initialFlexMode) => ({
    ...initialState,
    roleSelections: createRoleSelections(initialFlexMode),
  }));
  const [error, setError] = useState<string | null>(null);
  // Step errors stay hidden until the registrant tries to advance: the form used
  // to open with a red "BattleTag is required" and a dead Next button.
  const [advanceAttempted, setAdvanceAttempted] = useState(false);
  const [liveValidationErrors, setLiveValidationErrors] = useState<Record<string, string | null>>({});
  const stepRef = useRef<HTMLDivElement>(null);
  const stepErrorRef = useRef<HTMLParagraphElement>(null);
  // Admin-only: site account to anchor this registration on. Prefills empty
  // identity handles from the account's OAuth-verified logins on select.
  const [authUserId, setAuthUserId] = useState<number | undefined>(undefined);
  const [authUserLabel, setAuthUserLabel] = useState<string | undefined>(undefined);

  const handleSelectAuthUser = async (authUser: AuthUserOption | undefined) => {
    setAuthUserId(authUser?.id);
    setAuthUserLabel(authUser?.label);
    if (!authUser) return;
    try {
      const page = await rbacService.listOAuthConnections({ auth_user_id: authUser.id, per_page: -1 });
      const handleFor = (provider: string) => page.results.find((c) => c.provider === provider)?.username;
      const prefill: Array<[keyof UnifiedFormState, string | undefined, string]> = [
        ["battleTag", handleFor("battlenet"), state.battleTag],
        ["discordNick", handleFor("discord"), state.discordNick],
        ["twitchNick", handleFor("twitch"), state.twitchNick],
        ["boostyNick", handleFor("boosty"), state.boostyNick],
      ];
      for (const [key, handle, current] of prefill) {
        if (handle && !current.trim()) dispatch({ type: "SET_FIELD", key, value: handle });
      }
    } catch {
      // Best-effort prefill (e.g. missing auth_user:read); linking still works.
    }
  };

  const isEnabled = (fieldKey: string) => formConfig.built_in_fields?.[fieldKey]?.enabled !== false;
  const isRequired = (fieldKey: string) =>
    isEnabled(fieldKey) && formConfig.built_in_fields?.[fieldKey]?.required === true;
  const getBuiltInConfig = (fieldKey: string) => formConfig.built_in_fields?.[fieldKey];

  // Registrant's OAuth-verified accounts drive `require_verified` gating (public mode).
  const verifiedAccounts =
    mode === "public" ? (userProfile?.social_accounts ?? []).filter((a) => a.is_verified) : [];

  const topHeroesConfig = formConfig.built_in_fields?.top_heroes;
  const topHeroesEnabled = !!topHeroesConfig && topHeroesConfig.enabled !== false;
  const maxHeroes =
    topHeroesConfig?.max_heroes && topHeroesConfig.max_heroes > 0 ? topHeroesConfig.max_heroes : 5;

  /**
   * Only steps that actually have something to fill in are offered.
   *
   * The step list used to be a hard-coded three, so a tournament with no notes,
   * no stream POV and no custom fields still made the registrant click through a
   * "Details" step whose entire content was "No additional fields required".
   */
  const stepHasContent: Record<StepKey, boolean> = {
    accounts:
      mode === "admin" ||
      ["battle_tag", "smurf_tags", "discord_nick", "twitch_nick", "boosty_nick"].some(isEnabled),
    roles:
      mode === "admin" ||
      isEnabled("primary_role") ||
      isEnabled("additional_roles") ||
      isEnabled("flex_role") ||
      topHeroesEnabled,
    details:
      mode === "admin" ||
      isEnabled("notes") ||
      formConfig.built_in_fields?.stream_pov?.enabled === true ||
      formConfig.custom_fields.length > 0,
  };

  const allStepDefs: Array<{ key: StepKey; label: string }> = [
    { key: "accounts", label: mode === "admin" ? "Accounts" : t("registration.wizard.steps.accounts") },
    { key: "roles", label: mode === "admin" ? "Roles" : t("registration.wizard.steps.roles") },
    { key: "details", label: mode === "admin" ? "Details" : t("registration.wizard.steps.details") },
  ];
  const visibleSteps = allStepDefs.filter((step) => stepHasContent[step.key]);
  const STEPS = visibleSteps.length > 0 ? visibleSteps : [allStepDefs[0]];
  const stepIndex = Math.min(state.step, STEPS.length - 1);
  const stepKey = STEPS[stepIndex].key;

  const heroesQuery = useQuery({
    queryKey: ["heroes-all"],
    queryFn: () => heroService.getAll({ perPage: -1 }),
    enabled: topHeroesEnabled,
    staleTime: 5 * 60_000,
  });
  const allHeroes = heroesQuery.data?.results ?? [];

  // Map initial values. `formConfig` is read but deliberately not a dependency:
  // it is a fresh object on most parent renders, and re-running this effect
  // would overwrite whatever the operator has typed since.
  const publicPrefillApplied = useRef(false);
  useEffect(() => {
    if (mode === "admin" && initialData) {
      const initRanks: Record<string, string> = { tank: "", damage: "", support: "" };
      const roleSelections = createRoleSelections();

      for (const role of [...(initialData.roles ?? [])].sort((a, b) => a.priority - b.priority)) {
        const code = role.role;
        if (!(code in roleSelections)) {
          continue;
        }
        if (role.rank_value != null) {
          initRanks[code] = String(role.rank_value);
        }
        roleSelections[code] = {
          priority: role.is_primary ? "main" : "fallback",
          subrole: role.subrole ?? "",
          topHeroes: role.top_heroes ?? [],
        };
      }

      // Stored answers are typed JSON; the form state is all strings.
      const initCustomFields: Record<string, string> = {};
      for (const field of formConfig.custom_fields) {
        const stored = initialData.custom_fields_json?.[field.key];
        if (stored == null) continue;
        // Only JSON `true` or the string "true" counts as a checked box.
        initCustomFields[field.key] =
          field.type === "checkbox"
            ? String(stored === true || stored === "true")
            : String(stored);
      }

      dispatch({
        type: "INIT_VALUES",
        values: {
          displayName: initialData.display_name ?? "",
          battleTag: initialData.battle_tag ?? "",
          smurfTags: initialData.smurf_tags_json ?? [],
          discordNick: initialData.discord_nick ?? "",
          twitchNick: initialData.twitch_nick ?? "",
          boostyNick: initialData.boosty_nick ?? "",
          // Without these two the editor opened blank on data that exists and
          // the submit below wrote the blank back — a silent wipe on every save.
          notes: initialData.notes ?? "",
          customFieldsValues: initCustomFields,
          adminNotes: initialData.admin_notes ?? "",
          streamPov: initialData.stream_pov ?? false,
          status: initialData.status ?? "approved",
          balancerStatus: initialData.balancer_status ?? "not_in_balancer",
          roleSelections,
          ranks: initRanks,
        },
      });
    } else if (mode === "public" && userProfile && !publicPrefillApplied.current) {
      const init: Partial<UnifiedFormState> = {};
      const accounts = userProfile.social_accounts ?? [];
      const bts = accounts.filter((a) => a.provider === "battlenet").map((a) => a.username);
      const dcs = accounts.filter((a) => a.provider === "discord").map((a) => a.username);
      const tws = accounts.filter((a) => a.provider === "twitch").map((a) => a.username);
      const bss = accounts.filter((a) => a.provider === "boosty").map((a) => a.username);
      if (isEnabled("battle_tag") && bts.length > 0) init.battleTag = bts[0];
      if (isEnabled("discord_nick") && dcs.length > 0) init.discordNick = dcs[0];
      if (isEnabled("twitch_nick") && tws.length > 0) init.twitchNick = tws[0];
      if (isEnabled("boosty_nick") && bss.length > 0) init.boostyNick = bss[0];
      // The dispatch was missing outright, so this whole block computed a
      // prefill and threw it away. Applied once: a background refetch of the
      // profile must not stomp on handles the registrant has since edited.
      if (Object.keys(init).length > 0) {
        publicPrefillApplied.current = true;
        dispatch({ type: "INIT_VALUES", values: init });
      }
    }
  }, [mode, initialData, userProfile]);

  const getCurrentStepLiveValidationFieldKeys = (): string[] => {
    if (stepKey === "accounts") {
      return [
        ...(isEnabled("battle_tag") ? ["battle_tag"] : []),
        ...(isEnabled("smurf_tags") ? ["smurf_tags"] : []),
        ...(isEnabled("discord_nick") ? ["discord_nick"] : []),
        ...(isEnabled("twitch_nick") ? ["twitch_nick"] : []),
        ...(isEnabled("boosty_nick") ? ["boosty_nick"] : []),
      ];
    }
    if (stepKey === "details") {
      return [
        ...(isEnabled("notes") ? ["notes"] : []),
        ...formConfig.custom_fields.map((field) => field.key),
      ];
    }
    return [];
  };

  const verifiedFieldValues: Record<string, string> = {
    battle_tag: state.battleTag,
    discord_nick: state.discordNick,
    twitch_nick: state.twitchNick,
    boosty_nick: state.boostyNick,
  };
  // ``require_verified`` gates the registrant's own OAuth accounts; admin editing
  // is unconstrained (matches AccountStep, which renders a plain input in admin).
  const getVerifiedError = (fieldKey: string): string | null =>
    mode === "public" && isEnabled(fieldKey)
      ? getVerifiedFieldError(
          fieldKey,
          verifiedFieldValues[fieldKey] ?? "",
          getBuiltInConfig(fieldKey),
          verifiedAccounts,
          t
        )
      : null;

  const validateCurrentStep = (): string | null => {
    if (stepKey === "accounts") {
      // ``require_verified`` gating takes priority — it implies the field is required.
      const verifiedError =
        getVerifiedError("battle_tag") ??
        getVerifiedError("discord_nick") ??
        getVerifiedError("twitch_nick");
      if (verifiedError) {
        return verifiedError;
      }
      if (isRequired("battle_tag") && !state.battleTag.trim()) {
        return t("registration.wizard.validation.battleTagRequired");
      }
      if (isRequired("smurf_tags") && state.smurfTags.length === 0) {
        return t("registration.wizard.validation.smurfTagsRequired");
      }
      if (isRequired("discord_nick") && !state.discordNick.trim()) {
        return t("registration.wizard.validation.discordRequired");
      }
      if (isRequired("twitch_nick") && !state.twitchNick.trim()) {
        return t("registration.wizard.validation.twitchRequired");
      }
      if (isRequired("boosty_nick") && !state.boostyNick.trim()) {
        return t("registration.wizard.validation.boostyRequired");
      }
      return (
        (isEnabled("battle_tag")
          ? getBuiltInFieldValidationError(
              "battle_tag",
              state.battleTag,
              getBuiltInConfig("battle_tag"),
              t
            )
          : null) ??
        (isEnabled("smurf_tags")
          ? getBuiltInListValidationError(
              "smurf_tags",
              state.smurfTags,
              getBuiltInConfig("smurf_tags"),
              t
            )
          : null) ??
        (isEnabled("discord_nick")
          ? getBuiltInFieldValidationError(
              "discord_nick",
              state.discordNick,
              getBuiltInConfig("discord_nick"),
              t
            )
          : null) ??
        (isEnabled("twitch_nick")
          ? getBuiltInFieldValidationError(
              "twitch_nick",
              state.twitchNick,
              getBuiltInConfig("twitch_nick"),
              t
            )
          : null) ??
        (isEnabled("boosty_nick")
          ? getBuiltInFieldValidationError(
              "boosty_nick",
              state.boostyNick,
              getBuiltInConfig("boosty_nick"),
              t
            )
          : null)
      );
    }

    if (stepKey === "roles") {
      // A locked slot IS the answer to "which role", so the two rules that ask
      // for one (a main role, and a fallback alongside it) cannot apply: the
      // invitee has no second row to fill and no authority to change the first.
      const active = lockedRole
        ? ROLES.filter((role) => role.code === lockedRole)
        : ROLES.filter((role) => state.roleSelections[role.code].priority !== "off");
      if (!lockedRole) {
        const hasMain = active.some((role) => state.roleSelections[role.code].priority === "main");
        if ((isEnabled("primary_role") || isEnabled("additional_roles")) && !hasMain) {
          return t("registration.wizard.validation.primaryRoleRequired");
        }
        if (
          isRequired("additional_roles") &&
          !isFlexSelection(state.roleSelections) &&
          active.length < 2
        ) {
          return t("registration.wizard.validation.fallbackRoleRequired");
        }
      }
      if (topHeroesEnabled && topHeroesConfig?.required) {
        const hasHero = active.some((role) => state.roleSelections[role.code].topHeroes.length > 0);
        if (!hasHero) {
          return t("registration.wizard.validation.topHeroesRequired");
        }
      }
      return null;
    }

    if (isRequired("notes") && !state.notes.trim()) {
      return t("registration.wizard.validation.notesRequired");
    }
    const notesValidationError = getBuiltInFieldValidationError(
      "notes",
      state.notes,
      getBuiltInConfig("notes"),
      t
    );
    if (notesValidationError) {
      return notesValidationError;
    }

    for (const field of formConfig.custom_fields) {
      const rawValue = state.customFieldsValues[field.key] ?? "";
      const isFilled = field.type === "checkbox" ? true : rawValue.trim() !== "";
      // `required` is a rule for the registrant. An admin editing a row that
      // predates the definition must not be locked out of unrelated fixes, so
      // only the format check runs on both sides.
      if (mode === "public" && field.required && !isFilled) {
        return t("registration.wizard.validation.fieldRequired", { label: field.label });
      }
      const customFieldValidationError = getCustomFieldValidationError(field, rawValue, t);
      if (customFieldValidationError) {
        return customFieldValidationError;
      }
    }

    return null;
  };

  const currentStepValidationError =
    getFirstLiveValidationError(liveValidationErrors, getCurrentStepLiveValidationFieldKeys()) ??
    validateCurrentStep();
  // Field-level problems already render inline next to their control, wired via
  // `aria-invalid`/`aria-describedby`; the footer only carries step-level ones.
  const stepError = advanceAttempted ? currentStepValidationError : null;
  const roleStepError = stepKey === "roles" ? stepError : null;
  const footerError = error ?? (stepKey === "roles" ? null : stepError);

  // A locked slot submits exactly that role. Without this filter the two hidden
  // rows would still ride along if they carried a non-`off` priority from the
  // reducer's initial state, and the invitee would register for roles the team
  // never offered them.
  const payloadRoles = lockedRole ? ROLES.filter((role) => role.code === lockedRole) : ROLES;
  const orderedActiveRoles = payloadRoles
    .filter((role) => lockedRole != null || state.roleSelections[role.code].priority !== "off")
    .sort((a, b) => {
    const rank = (code: RoleCode) => (state.roleSelections[code].priority === "main" ? 0 : 1);
    return rank(a.code) - rank(b.code);
  });

  const buildRolesPayload = (): RoleInput[] =>
    orderedActiveRoles.map((role) => {
      const selection = state.roleSelections[role.code];
      return {
        role: role.code,
        ...(selection.subrole ? { subrole: selection.subrole } : {}),
        // A locked slot is always primary: it is the one role the invite bought,
        // and `RoleStep` hides the priority control that could say otherwise.
        is_primary: lockedRole != null || selection.priority === "main",
        ...(selection.topHeroes.length > 0 ? { top_heroes: selection.topHeroes } : {}),
      };
    });

  /**
   * Custom-field answers in the shape both APIs store: string values keyed by
   * definition key, empty answers omitted so clearing a field clears the stored
   * one. Shared, because the admin editor used to send no custom fields at all.
   */
  const buildCustomFieldsPayload = (): Record<string, string> =>
    Object.fromEntries(
      formConfig.custom_fields
        .map((field) => [
          field.key,
          field.type === "checkbox"
            ? String(state.customFieldsValues[field.key] === "true")
            : (state.customFieldsValues[field.key] ?? ""),
        ])
        .filter(([, value]) => value !== "")
    );

  const focusFirstProblem = () => {
    const invalid = stepRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
    (invalid ?? stepErrorRef.current)?.focus();
  };

  // Build the unified payload on submit
  const handleNext = () => {
    if (currentStepValidationError) {
      setAdvanceAttempted(true);
      // Let the alert render before moving focus into it.
      requestAnimationFrame(focusFirstProblem);
      return;
    }

    const isLastStep = stepIndex === STEPS.length - 1;
    if (!isLastStep) {
      setAdvanceAttempted(false);
      dispatch({ type: "SET_STEP", step: stepIndex + 1 });
      return;
    }

    const rolesPayload = buildRolesPayload();

    if (mode === "public") {
      onSubmit({
        battle_tag: isEnabled("battle_tag") ? (state.battleTag || undefined) : undefined,
        smurf_tags: isEnabled("smurf_tags") && state.smurfTags.length > 0 ? state.smurfTags : undefined,
        discord_nick: isEnabled("discord_nick") ? (state.discordNick || undefined) : undefined,
        twitch_nick: isEnabled("twitch_nick") ? (state.twitchNick || undefined) : undefined,
        boosty_nick: isEnabled("boosty_nick") ? (state.boostyNick || undefined) : undefined,
        roles: rolesPayload.length > 0 ? rolesPayload : undefined,
        stream_pov: isEnabled("stream_pov") ? state.streamPov : undefined,
        notes: isEnabled("notes") ? (state.notes || undefined) : undefined,
        custom_fields: buildCustomFieldsPayload(),
      });
      return;
    }

    onSubmit({
      display_name: state.displayName || null,
      battle_tag: state.battleTag || null,
      smurf_tags_json: state.smurfTags,
      discord_nick: state.discordNick || null,
      twitch_nick: state.twitchNick || null,
      boosty_nick: state.boostyNick || null,
      notes: state.notes || null,
      custom_fields_json: buildCustomFieldsPayload(),
      admin_notes: state.adminNotes || null,
      is_flex: isFlexSelection(state.roleSelections),
      stream_pov: state.streamPov,
      status: state.status,
      balancer_status: state.balancerStatus,
      roles: orderedActiveRoles.map((role, index) => {
        const selection = state.roleSelections[role.code];
        const rankStr = state.ranks[role.code] ?? "";
        const parsedRankValue = rankStr.trim() ? Number(rankStr) : null;
        return {
          role: role.code,
          subrole: selection.subrole || null,
          is_primary: selection.priority === "main",
          priority: index + 1,
          rank_value: Number.isFinite(parsedRankValue) ? parsedRankValue : null,
          is_active: true,
          ...(selection.topHeroes.length > 0 ? { top_heroes: selection.topHeroes } : {}),
        };
      }),
      auth_user_id: authUserId ?? null,
    });
  };

  const handleBack = () => {
    setError(null);
    setAdvanceAttempted(false);
    dispatch({ type: "SET_STEP", step: stepIndex - 1 });
  };

  const handleFieldUpdate = (key: string, value: string) => {
    setError(null);
    if (key === "battle_tag") dispatch({ type: "SET_FIELD", key: "battleTag", value });
    else if (key === "discord_nick") dispatch({ type: "SET_FIELD", key: "discordNick", value });
    else if (key === "twitch_nick") dispatch({ type: "SET_FIELD", key: "twitchNick", value });
    else if (key === "boosty_nick") dispatch({ type: "SET_FIELD", key: "boostyNick", value });
    else if (key === "notes") dispatch({ type: "SET_FIELD", key: "notes", value });
    else if (key === "stream_pov") dispatch({ type: "SET_FIELD", key: "streamPov", value: value === "true" });
    else dispatch({ type: "SET_CUSTOM_FIELD", key, value });
  };

  const handleSmurfTagsChange = (tags: string[]) => {
    setError(null);
    dispatch({ type: "SET_FIELD", key: "smurfTags", value: tags });
  };

  const handleBuiltInValidationChange = (fieldKey: string, nextError: string | null) => {
    setLiveValidationErrors((prev) => {
      if (prev[fieldKey] === nextError) {
        return prev;
      }
      return { ...prev, [fieldKey]: nextError };
    });
  };

  // Suggestions mapping (from the player's unified social accounts)
  const profileAccounts = userProfile?.social_accounts ?? [];
  const battleTagSuggestions = profileAccounts.filter((a) => a.provider === "battlenet").map((a) => a.username);
  const discordSuggestions = profileAccounts.filter((a) => a.provider === "discord").map((a) => a.username);
  const twitchSuggestions = profileAccounts.filter((a) => a.provider === "twitch").map((a) => a.username);
  const boostySuggestions = profileAccounts.filter((a) => a.provider === "boosty").map((a) => a.username);

  // Subscription standing for the chips, the rule notice and the submit block.
  // Public mode only: the endpoint answers for the CALLER, so it is meaningless
  // while an admin edits somebody else's registration.
  const subscriptionQuery = useQuery({
    queryKey: tournamentQueryKeys.subscriptionStatus(tournamentId),
    queryFn: () => registrationService.getMySubscriptionStatus(tournamentId),
    enabled: mode === "public" && formConfig.require_subscription === true,
    staleTime: 30_000,
  });

  // The server refuses this submit, and no field on this form can change that:
  // `blocks_registration` is already narrowed to the automatically-decided part
  // of the rule, so anything a challenge code could still fix is NOT in here —
  // that is asked for at check-in. Disabling beats letting three steps be filled
  // in and answering 400.
  const subscriptionBlocked = subscriptionQuery.data?.blocks_registration === true;

  // Setup options for admin selects
  const resolvedRegistrationStatusOptions = {
    system: [
      { value: "pending", name: "Pending" },
      { value: "approved", name: "Approved" },
      { value: "rejected", name: "Rejected" },
      { value: "withdrawn", name: "Withdrawn" },
      { value: "banned", name: "Banned" },
      { value: "insufficient_data", name: "Incomplete" },
    ],
    custom:
      initialData?.status_meta?.kind === "custom"
        ? [{ value: initialData.status ?? "", name: initialData.status_meta.name }]
        : [],
  };

  const resolvedBalancerStatusOptions = {
    system: [
      { value: "not_in_balancer", name: "Not Added" },
      { value: "incomplete", name: "Incomplete" },
      { value: "ready", name: "Ready" },
    ],
    custom:
      initialData?.balancer_status_meta?.kind === "custom"
        ? [{ value: initialData.balancer_status ?? "", name: initialData.balancer_status_meta.name }]
        : [],
  };

  const isLastStep = stepIndex === STEPS.length - 1;

  return (
    <div className="flex flex-col gap-4">
      {mode === "public" && !hideTitle && (
        <h2 className="text-lg font-semibold text-[color:var(--aqt-fg)]">
          {tournamentName
            ? t("registration.wizard.titleFor", { name: tournamentName })
            : t("registration.wizard.title")}
        </h2>
      )}

      {STEPS.length > 1 && <StepIndicator steps={STEPS} current={stepIndex} />}

      <div ref={stepRef}>
        {stepKey === "accounts" && mode === "admin" && (
          <div className="mb-4 space-y-1.5">
            <h3 className="text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
              Linked Site Account
            </h3>
            <AuthUserSearchCombobox
              value={authUserId}
              selectedLabel={authUserLabel}
              onSelect={handleSelectAuthUser}
            />
            <p className="text-xs leading-5 text-[color:var(--aqt-fg-muted)]">
              Optional. Anchors this registration on the selected account; empty handles are prefilled
              from its verified logins.
            </p>
          </div>
        )}
        {stepKey === "accounts" && (
          <AccountStep
            mode={mode}
            displayName={state.displayName}
            onDisplayNameChange={(v) => dispatch({ type: "SET_FIELD", key: "displayName", value: v })}
            values={{
              battle_tag: state.battleTag,
              discord_nick: state.discordNick,
              twitch_nick: state.twitchNick,
              boosty_nick: state.boostyNick,
            }}
            onUpdate={handleFieldUpdate}
            smurfTags={state.smurfTags}
            onSmurfTagsChange={handleSmurfTagsChange}
            onBuiltInValidationChange={handleBuiltInValidationChange}
            form={formConfig}
            battleTagSuggestions={mode === "admin" ? [] : battleTagSuggestions}
            discordSuggestions={mode === "admin" ? [] : discordSuggestions}
            twitchSuggestions={mode === "admin" ? [] : twitchSuggestions}
            boostySuggestions={mode === "admin" ? [] : boostySuggestions}
            subscription={mode === "public" ? subscriptionQuery.data : null}
            accounts={mode === "admin" ? [] : (userProfile?.social_accounts ?? [])}
            verifiedErrors={{
              battle_tag: getVerifiedError("battle_tag"),
              discord_nick: getVerifiedError("discord_nick"),
              twitch_nick: getVerifiedError("twitch_nick"),
            }}
            onLinkAccounts={
              mode === "public"
                ? () => {
                    // Close registration and open profile settings on the
                    // "My Account" tab. Linking there redirects through OAuth
                    // and returns via ?settings=profile (AccountSettingsModal).
                    onCancel();
                    openAccountSettings("profile");
                  }
                : undefined
            }
          />
        )}

        {stepKey === "roles" && (
          <RoleStep
            selections={state.roleSelections}
            onChange={(selections) => dispatch({ type: "SET_ROLES", selections })}
            error={roleStepError}
            form={formConfig}
            allHeroes={allHeroes}
            topHeroesEnabled={topHeroesEnabled}
            maxHeroes={maxHeroes}
            flexMode={flexMode}
            hideHelperText={mode === "admin"}
            lockedRole={lockedRole}
          />
        )}

        {stepKey === "details" && (
          <DetailsStep
            mode={mode}
            values={{
              notes: state.notes,
              stream_pov: state.streamPov ? "true" : "false",
              ...state.customFieldsValues,
            }}
            onUpdate={handleFieldUpdate}
            onFieldValidationChange={handleBuiltInValidationChange}
            form={formConfig}
            adminNotes={state.adminNotes}
            onAdminNotesChange={(v) => dispatch({ type: "SET_FIELD", key: "adminNotes", value: v })}
            status={state.status}
            onStatusChange={(v) => dispatch({ type: "SET_FIELD", key: "status", value: v })}
            balancerStatus={state.balancerStatus}
            onBalancerStatusChange={(v) => dispatch({ type: "SET_FIELD", key: "balancerStatus", value: v })}
            registrationStatusOptions={resolvedRegistrationStatusOptions}
            balancerStatusOptions={resolvedBalancerStatusOptions}
          />
        )}
      </div>

      {footerError && (
        <p
          ref={stepErrorRef}
          role="alert"
          tabIndex={-1}
          className="text-sm text-destructive focus-visible:outline-none"
        >
          {footerError}
        </p>
      )}

      {subscriptionBlocked && (
        <p
          role="alert"
          className="rounded-lg border border-[color:color-mix(in_srgb,var(--aqt-rose)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-rose)_12%,transparent)] p-2.5 text-xs leading-5 text-[color:var(--aqt-fg)]"
        >
          {t("common.subscription.registrationBlocked", {
            rule: subscriptionQuery.data?.rule ?? "",
          })}
        </p>
      )}

      <div className="flex items-center justify-between border-t border-[color:var(--aqt-border)] pt-4">
        {stepIndex > 0 ? (
          <button
            type="button"
            onClick={handleBack}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border-2)] px-3 py-2 text-sm font-medium text-[color:var(--aqt-fg-muted)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <ArrowLeft className="size-3.5" aria-hidden />
            {mode === "admin" ? "Back" : t("common.back")}
          </button>
        ) : (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-[color:var(--aqt-border-2)] px-3 py-2 text-sm font-medium text-[color:var(--aqt-fg-muted)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            {mode === "admin" ? "Cancel" : t("common.cancel")}
          </button>
        )}

        <button
          type="button"
          onClick={handleNext}
          disabled={submitPending || (isLastStep && subscriptionBlocked)}
          className="inline-flex items-center gap-2 rounded-lg bg-[color:var(--aqt-teal)] px-4 py-2 text-sm font-medium text-[color:var(--aqt-bg)] transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:opacity-50"
        >
          {submitPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
          {isLastStep ? (
            mode === "admin" ? (initialData ? "Save" : "Create") : t("common.submit")
          ) : (
            <>
              {mode === "admin" ? "Next" : t("common.next")}
              <ArrowRight className="size-3.5" aria-hidden />
            </>
          )}
        </button>
      </div>
    </div>
  );
}
