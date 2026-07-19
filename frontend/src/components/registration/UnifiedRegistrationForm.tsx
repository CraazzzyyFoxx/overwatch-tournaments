"use client";

import { useEffect, useReducer, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import heroService from "@/services/hero.service";
import { useTranslations } from "next-intl";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import type {
  RegistrationForm,
  RoleInput,
} from "@/types/registration.types";
import type { AdditionalRole } from "./types";
import type { User } from "@/types/user.types";
import type { AdminRegistration, BalancerRoleCode, BalancerRoleSubtype } from "@/types/balancer-admin.types";

import { AuthUserSearchCombobox, type AuthUserOption } from "@/components/admin/AuthUserSearchCombobox";
import { rbacService } from "@/services/rbac.service";
import StepIndicator from "@/components/registration/StepIndicator";
import AccountStep from "@/components/registration/AccountStep";
import RoleStep from "@/components/registration/RoleStep";
import DetailsStep from "@/components/registration/DetailsStep";
import { ROLES } from "@/lib/roles";
import {
  getFirstLiveValidationError,
  getStepDisplayValidationError,
  getBuiltInFieldValidationError,
  getBuiltInListValidationError,
  getCustomFieldValidationError,
  getVerifiedFieldError,
} from "@/components/registration/validation";

interface UnifiedFormState {
  step: number;
  displayName: string;
  battleTag: string;
  smurfTags: string[];
  discordNick: string;
  twitchNick: string;
  notes: string;
  adminNotes: string;
  isFlex: boolean;
  streamPov: boolean;
  status: string;
  balancerStatus: string;
  primaryRole: string;
  subrole: string;
  additionalRoles: AdditionalRole[];
  primaryRoleHeroes: string[];
  flexHeroes: string[];
  // rank values map by role
  ranks: Record<string, string>;
  // Custom fields
  customFieldsValues: Record<string, string>;
}

type UnifiedFormAction =
  | { type: "SET_STEP"; step: number }
  | { type: "SET_FIELD"; key: keyof UnifiedFormState; value: any }
  | { type: "SET_RANK"; role: string; value: string }
  | { type: "SET_CUSTOM_FIELD"; key: string; value: string }
  | { type: "SET_FLEX"; isFlex: boolean }
  | { type: "SET_PRIMARY_ROLE"; role: string }
  | { type: "SET_SUBROLE"; subrole: string }
  | { type: "SET_ADDITIONAL_ROLES"; roles: AdditionalRole[] }
  | { type: "SET_PRIMARY_ROLE_HEROES"; heroes: string[] }
  | { type: "SET_FLEX_HEROES"; heroes: string[] }
  | { type: "INIT_VALUES"; values: Partial<UnifiedFormState> };

const initialState: UnifiedFormState = {
  step: 0,
  displayName: "",
  battleTag: "",
  smurfTags: [],
  discordNick: "",
  twitchNick: "",
  notes: "",
  adminNotes: "",
  isFlex: false,
  streamPov: false,
  status: "approved",
  balancerStatus: "not_in_balancer",
  primaryRole: "",
  subrole: "",
  additionalRoles: [],
  primaryRoleHeroes: [],
  flexHeroes: [],
  ranks: { tank: "", dps: "", support: "" },
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
    case "SET_FLEX":
      return {
        ...state,
        isFlex: action.isFlex,
        ...(action.isFlex
          ? { primaryRole: "", subrole: "", additionalRoles: [], primaryRoleHeroes: [] }
          : {}),
      };
    case "SET_PRIMARY_ROLE":
      return { ...state, primaryRole: action.role, isFlex: false, primaryRoleHeroes: [] };
    case "SET_SUBROLE":
      return { ...state, subrole: action.subrole };
    case "SET_ADDITIONAL_ROLES":
      return { ...state, additionalRoles: action.roles };
    case "SET_PRIMARY_ROLE_HEROES":
      return { ...state, primaryRoleHeroes: action.heroes };
    case "SET_FLEX_HEROES":
      return { ...state, flexHeroes: action.heroes };
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
}

export default function UnifiedRegistrationForm({
  mode,
  tournamentId,
  workspaceId,
  formConfig,
  tournamentName,
  initialData,
  userProfile,
  onSubmit,
  onCancel,
  submitPending = false,
}: UnifiedRegistrationFormProps) {
  const t = useTranslations();
  const openAccountSettings = useAccountSettingsModalStore((s) => s.open);
  const [state, dispatch] = useReducer(formReducer, initialState);
  const [error, setError] = useState<string | null>(null);
  const [liveValidationErrors, setLiveValidationErrors] = useState<Record<string, string | null>>({});
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
  const flexEnabled = formConfig.built_in_fields?.flex_role?.enabled !== false;

  // i18n and display steps
  const STEPS = [
    { label: mode === "admin" ? "Accounts" : t("registration.wizard.steps.accounts") },
    { label: mode === "admin" ? "Roles" : t("registration.wizard.steps.roles") },
    { label: mode === "admin" ? "Details" : t("registration.wizard.steps.details") },
  ];

  const heroesQuery = useQuery({
    queryKey: ["heroes-all"],
    queryFn: () => heroService.getAll({ perPage: -1 }),
    enabled: topHeroesEnabled,
    staleTime: 5 * 60_000,
  });
  const allHeroes = heroesQuery.data?.results ?? [];

  // Map initial values
  useEffect(() => {
    if (mode === "admin" && initialData) {
      const initRanks: Record<string, string> = { tank: "", dps: "", support: "" };
      const initRoles: AdditionalRole[] = [];
      let isFlex = initialData.is_flex ?? false;
      let primaryRole = "";
      let subrole = "";
      let primaryRoleHeroes: string[] = [];
      let flexHeroes: string[] = [];

      if (initialData.roles) {
        // Sort roles so primary comes first or by priority
        const sorted = [...initialData.roles].sort((a, b) => a.priority - b.priority);
        for (const role of sorted) {
          const roleHeroes = (role as any).top_heroes ?? [];
          if (role.rank_value != null) {
            initRanks[role.role] = String(role.rank_value);
          }
          if (isFlex) {
            if (roleHeroes.length > 0) {
              flexHeroes = roleHeroes;
            }
          } else {
            if (role.is_primary) {
              primaryRole = role.role;
              subrole = role.subrole ?? "";
              primaryRoleHeroes = roleHeroes;
            } else {
              initRoles.push({
                code: role.role,
                subrole: role.subrole ?? "",
                topHeroes: roleHeroes,
              });
            }
          }
        }
      }

      dispatch({
        type: "INIT_VALUES",
        values: {
          displayName: initialData.display_name ?? "",
          battleTag: initialData.battle_tag ?? "",
          smurfTags: initialData.smurf_tags_json ?? [],
          discordNick: initialData.discord_nick ?? "",
          twitchNick: initialData.twitch_nick ?? "",
          notes: initialData.notes ?? "",
          adminNotes: initialData.admin_notes ?? "",
          isFlex,
          streamPov: initialData.stream_pov ?? false,
          status: initialData.status ?? "approved",
          balancerStatus: initialData.balancer_status ?? "not_in_balancer",
          primaryRole,
          subrole,
          additionalRoles: initRoles,
          ranks: initRanks,
          primaryRoleHeroes,
          flexHeroes,
        },
      });
    } else if (mode === "public" && userProfile) {
      const init: Partial<UnifiedFormState> = {};
      const accounts = userProfile.social_accounts ?? [];
      const bts = accounts.filter((a) => a.provider === "battlenet").map((a) => a.username);
      const dcs = accounts.filter((a) => a.provider === "discord").map((a) => a.username);
      const tws = accounts.filter((a) => a.provider === "twitch").map((a) => a.username);
      if (isEnabled("battle_tag") && bts.length > 0) init.battleTag = bts[0];
      if (isEnabled("discord_nick") && dcs.length > 0) init.discordNick = dcs[0];
      if (isEnabled("twitch_nick") && tws.length > 0) init.twitchNick = tws[0];
      dispatch({ type: "INIT_VALUES", values: init });
    }
  }, [mode, initialData, userProfile]);

  // Validation strings
  const PRIMARY_ROLE_REQUIRED_ERROR = t("registration.wizard.validation.primaryRoleRequired");
  const ADDITIONAL_ROLES_REQUIRED_ERROR = t("registration.wizard.validation.fallbackRoleRequired");
  const TOP_HEROES_REQUIRED_ERROR = t("registration.wizard.validation.topHeroesRequired");

  const getCurrentStepLiveValidationFieldKeys = (): string[] => {
    if (state.step === 0) {
      return [
        ...(isEnabled("battle_tag") ? ["battle_tag"] : []),
        ...(isEnabled("smurf_tags") ? ["smurf_tags"] : []),
        ...(isEnabled("discord_nick") ? ["discord_nick"] : []),
        ...(isEnabled("twitch_nick") ? ["twitch_nick"] : []),
      ];
    }
    if (state.step === 2) {
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
    if (state.step === 0) {
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
          : null)
      );
    }

    if (state.step === 1) {
      const requiresAnyRole = isEnabled("primary_role") || isEnabled("additional_roles");
      if (requiresAnyRole && !state.isFlex && !state.primaryRole) {
        return PRIMARY_ROLE_REQUIRED_ERROR;
      }
      if (isRequired("additional_roles") && !state.isFlex && state.additionalRoles.length === 0) {
        return ADDITIONAL_ROLES_REQUIRED_ERROR;
      }
      if (topHeroesEnabled && topHeroesConfig?.required) {
        const hasHero = state.isFlex
          ? state.flexHeroes.length > 0
          : state.primaryRoleHeroes.length > 0 ||
            state.additionalRoles.some((entry) => entry.topHeroes.length > 0);
        if (!hasHero) {
          return TOP_HEROES_REQUIRED_ERROR;
        }
      }
      return null;
    }

    if (state.step === 2) {
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

      if (mode === "public") {
        for (const field of formConfig.custom_fields) {
          const rawValue = state.customFieldsValues[field.key] ?? "";
          const isFilled = field.type === "checkbox" ? true : rawValue.trim() !== "";
          if (field.required && !isFilled) {
            return t("registration.wizard.validation.fieldRequired", { label: field.label });
          }
          const customFieldValidationError = getCustomFieldValidationError(field, rawValue, t);
          if (customFieldValidationError) {
            return customFieldValidationError;
          }
        }
      }
    }

    return null;
  };

  const currentStepLiveValidationError = getFirstLiveValidationError(
    liveValidationErrors,
    getCurrentStepLiveValidationFieldKeys()
  );
  const currentStepBaseValidationError = validateCurrentStep();
  const currentStepValidationError = currentStepLiveValidationError ?? currentStepBaseValidationError;
  const currentStepDisplayValidationError = getStepDisplayValidationError(
    currentStepLiveValidationError,
    currentStepBaseValidationError
  );
  const roleStepPrimaryError =
    state.step === 1 && currentStepDisplayValidationError === PRIMARY_ROLE_REQUIRED_ERROR
      ? currentStepDisplayValidationError
      : null;
  const roleStepSecondaryError =
    state.step === 1 && currentStepDisplayValidationError === ADDITIONAL_ROLES_REQUIRED_ERROR
      ? currentStepDisplayValidationError
      : null;
  const footerValidationError =
    currentStepDisplayValidationError === roleStepPrimaryError ||
    currentStepDisplayValidationError === roleStepSecondaryError
      ? null
      : currentStepDisplayValidationError;

  const buildRolesPayload = (): RoleInput[] => {
    if (state.isFlex) {
      return ROLES.map((r) => ({
        role: r.code,
        is_primary: true,
        ...(state.flexHeroes.length > 0 ? { top_heroes: state.flexHeroes } : {}),
      }));
    }
    const roles: RoleInput[] = [];
    if (state.primaryRole) {
      roles.push({
        role: state.primaryRole,
        ...(state.subrole ? { subrole: state.subrole } : {}),
        is_primary: true,
        ...(state.primaryRoleHeroes.length > 0 ? { top_heroes: state.primaryRoleHeroes } : {}),
      });
    }
    for (const ar of state.additionalRoles) {
      roles.push({
        role: ar.code,
        ...(ar.subrole ? { subrole: ar.subrole } : {}),
        is_primary: false,
        ...(ar.topHeroes.length > 0 ? { top_heroes: ar.topHeroes } : {}),
      });
    }
    return roles;
  };

  // Build the unified payload on submit
  const handleNext = () => {
    if (currentStepValidationError) {
      return;
    }

    const isLastStep = state.step === STEPS.length - 1;
    if (isLastStep) {
      const rolesPayload = buildRolesPayload();

      if (mode === "public") {
        const payload = {
          battle_tag: isEnabled("battle_tag") ? (state.battleTag || undefined) : undefined,
          smurf_tags: isEnabled("smurf_tags") && state.smurfTags.length > 0 ? state.smurfTags : undefined,
          discord_nick: isEnabled("discord_nick") ? (state.discordNick || undefined) : undefined,
          twitch_nick: isEnabled("twitch_nick") ? (state.twitchNick || undefined) : undefined,
          roles: rolesPayload.length > 0 ? rolesPayload : undefined,
          stream_pov: isEnabled("stream_pov") ? state.streamPov : undefined,
          notes: isEnabled("notes") ? (state.notes || undefined) : undefined,
          custom_fields: Object.fromEntries(
            formConfig.custom_fields
              .map((f) => [
                f.key,
                f.type === "checkbox"
                  ? (state.customFieldsValues[f.key] === "true" ? "true" : "false")
                  : (state.customFieldsValues[f.key] ?? ""),
              ])
              .filter(([, v]) => v !== "")
          ),
        };
        onSubmit(payload);
      } else {
        // Admin payloads
        const buildAdminRolePayload = (): any[] => {
          const enabledRoles = ROLES.filter((r) => {
            if (state.isFlex) return true;
            return r.code === state.primaryRole || state.additionalRoles.some((ar) => ar.code === r.code);
          }).map((r) => r.code);

          return enabledRoles.map((roleCode, index) => {
            const isPrimary = state.isFlex || state.primaryRole === roleCode;
            const rankStr = state.ranks[roleCode] ?? "";
            const parsedRankValue = rankStr.trim() ? Number(rankStr) : null;
            const entry = state.additionalRoles.find((ar) => ar.code === roleCode);
            const sub = isPrimary ? state.subrole : (entry?.subrole ?? "");

            let topHeroes: string[] = [];
            if (state.isFlex) {
              topHeroes = state.flexHeroes;
            } else if (isPrimary) {
              topHeroes = state.primaryRoleHeroes;
            } else if (entry) {
              topHeroes = entry.topHeroes;
            }

            return {
              role: roleCode,
              subrole: sub || null,
              is_primary: isPrimary,
              priority: index + 1,
              rank_value: Number.isFinite(parsedRankValue) ? parsedRankValue : null,
              is_active: true,
              ...(topHeroes.length > 0 ? { top_heroes: topHeroes } : {}),
            };
          });
        };

        const payload = {
          display_name: state.displayName || null,
          battle_tag: state.battleTag || null,
          smurf_tags_json: state.smurfTags,
          discord_nick: state.discordNick || null,
          twitch_nick: state.twitchNick || null,
          notes: state.notes || null,
          admin_notes: state.adminNotes || null,
          is_flex: state.isFlex,
          stream_pov: state.streamPov,
          status: state.status,
          balancer_status: state.balancerStatus,
          roles: buildAdminRolePayload(),
          auth_user_id: authUserId ?? null,
        };
        onSubmit(payload);
      }
    } else {
      dispatch({ type: "SET_STEP", step: state.step + 1 });
    }
  };

  const handleBack = () => {
    setError(null);
    dispatch({ type: "SET_STEP", step: state.step - 1 });
  };

  const handleFieldUpdate = (key: string, value: string) => {
    setError(null);
    if (key === "battle_tag") dispatch({ type: "SET_FIELD", key: "battleTag", value });
    else if (key === "discord_nick") dispatch({ type: "SET_FIELD", key: "discordNick", value });
    else if (key === "twitch_nick") dispatch({ type: "SET_FIELD", key: "twitchNick", value });
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

  // Setup options for admin selects
  const registrationStatusOptions = {
    system: [
      { value: "pending", name: "Pending" },
      { value: "approved", name: "Approved" },
      { value: "rejected", name: "Rejected" },
      { value: "withdrawn", name: "Withdrawn" },
      { value: "banned", name: "Banned" },
      { value: "insufficient_data", name: "Incomplete" },
    ],
    custom: [], // Can be populated dynamically if custom options are loaded
  };

  const balancerStatusOptions = {
    system: [
      { value: "not_in_balancer", name: "Not Added" },
      { value: "incomplete", name: "Incomplete" },
      { value: "ready", name: "Ready" },
    ],
    custom: [],
  };

  const isLastStep = state.step === STEPS.length - 1;

  // Admin select custom status options merging if initialData contains custom options
  const resolvedRegistrationStatusOptions = {
    system: registrationStatusOptions.system,
    custom: initialData?.status_meta?.kind === "custom" 
      ? [{ value: initialData.status ?? "", name: initialData.status_meta.name }]
      : [],
  };

  const resolvedBalancerStatusOptions = {
    system: balancerStatusOptions.system,
    custom: initialData?.balancer_status_meta?.kind === "custom"
      ? [{ value: initialData.balancer_status ?? "", name: initialData.balancer_status_meta.name }]
      : [],
  };

  return (
    <div className="flex flex-col gap-5 sm:min-h-[560px] lg:min-h-[640px]">
      {mode === "public" && (
        <div>
          <h2 className="text-lg font-semibold text-[color:var(--aqt-fg)]">
            {tournamentName
              ? t("registration.wizard.titleFor", { name: tournamentName })
              : t("registration.wizard.title")}
          </h2>
          <p className="mt-1 text-sm text-[color:var(--aqt-fg-muted)]">
            {state.step === 0 && t("registration.wizard.step1Desc")}
            {state.step === 1 && t("registration.wizard.step2Desc")}
            {state.step === 2 && t("registration.wizard.step3Desc")}
          </p>
        </div>
      )}

      <StepIndicator steps={STEPS} current={state.step} />

      <div className="flex-1">
        {state.step === 0 && mode === "admin" && (
          <div className="mb-4 space-y-1.5">
            <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-[color:var(--aqt-fg-muted)]">
              Linked Site Account
            </h3>
            <AuthUserSearchCombobox
              value={authUserId}
              selectedLabel={authUserLabel}
              onSelect={handleSelectAuthUser}
            />
            <p className="text-xs leading-5 text-[color:var(--aqt-fg-dim)]">
              Optional. Anchors this registration on the selected account; empty handles are prefilled
              from its verified logins.
            </p>
          </div>
        )}
        {state.step === 0 && (
          <AccountStep
            mode={mode}
            displayName={state.displayName}
            onDisplayNameChange={(v) => dispatch({ type: "SET_FIELD", key: "displayName", value: v })}
            values={{
              battle_tag: state.battleTag,
              discord_nick: state.discordNick,
              twitch_nick: state.twitchNick,
            }}
            onUpdate={handleFieldUpdate}
            smurfTags={state.smurfTags}
            onSmurfTagsChange={handleSmurfTagsChange}
            onBuiltInValidationChange={handleBuiltInValidationChange}
            form={formConfig}
            battleTagSuggestions={mode === "admin" ? [] : battleTagSuggestions}
            discordSuggestions={mode === "admin" ? [] : discordSuggestions}
            twitchSuggestions={mode === "admin" ? [] : twitchSuggestions}
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

        {state.step === 1 && (
          <RoleStep
            isFlex={state.isFlex}
            primaryRole={state.primaryRole}
            subrole={state.subrole}
            additionalRoles={state.additionalRoles}
            onSetFlex={(isFlex) => dispatch({ type: "SET_FLEX", isFlex })}
            onSetPrimaryRole={(role) => dispatch({ type: "SET_PRIMARY_ROLE", role })}
            onSetSubrole={(subrole) => dispatch({ type: "SET_SUBROLE", subrole })}
            onSetAdditionalRoles={(roles) => dispatch({ type: "SET_ADDITIONAL_ROLES", roles })}
            primaryRoleError={roleStepPrimaryError}
            secondaryRolesError={roleStepSecondaryError}
            form={formConfig}
            allHeroes={allHeroes}
            topHeroesEnabled={topHeroesEnabled}
            maxHeroes={maxHeroes}
            flexEnabled={flexEnabled}
            primaryRoleHeroes={state.primaryRoleHeroes}
            onSetPrimaryRoleHeroes={(heroes) => dispatch({ type: "SET_PRIMARY_ROLE_HEROES", heroes })}
            flexHeroes={state.flexHeroes}
            onSetFlexHeroes={(heroes) => dispatch({ type: "SET_FLEX_HEROES", heroes })}
            hideHelperText={mode === "admin"}
          />
        )}

        {state.step === 2 && (
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

      {(error || footerValidationError) && (
        <p className="text-sm text-red-400">{error ?? footerValidationError}</p>
      )}

      <div className="flex items-center justify-between border-t border-[color:var(--aqt-border)] pt-4">
        {state.step > 0 ? (
          <button
            type="button"
            onClick={handleBack}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border-2)] px-3 py-2 text-sm font-medium text-[color:var(--aqt-fg-muted)] transition-colors hover:bg-white/4"
          >
            <ArrowLeft className="size-3.5" />
            {mode === "admin" ? "Back" : t("common.back")}
          </button>
        ) : (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-[color:var(--aqt-border-2)] px-3 py-2 text-sm font-medium text-[color:var(--aqt-fg-muted)] transition-colors hover:bg-white/4"
          >
            {mode === "admin" ? "Cancel" : t("common.cancel")}
          </button>
        )}

        <button
          type="button"
          onClick={handleNext}
          disabled={submitPending || Boolean(currentStepValidationError)}
          className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {submitPending && <Loader2 className="size-4 animate-spin" />}
          {isLastStep ? (
            mode === "admin" ? (initialData ? "Save" : "Create") : t("common.submit")
          ) : (
            <>
              {mode === "admin" ? "Next" : t("common.next")}
              <ArrowRight className="size-3.5" />
            </>
          )}
        </button>
      </div>
    </div>
  );
}
