"use client";

import { useEffect, useReducer, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";

import { useAuthProfile } from "@/hooks/useAuthProfile";
import registrationService from "@/services/registration.service";
import userService from "@/services/user.service";
import type {
  RegistrationCreateInput,
  RegistrationForm,
} from "@/types/registration.types";
import type { User } from "@/types/user.types";

import { ROLES } from "@/lib/roles";
import type { AdditionalRole, WizardAction, WizardState } from "./types";
import StepIndicator from "./StepIndicator";
import AccountStep from "./AccountStep";
import RoleStep from "./RoleStep";
import DetailsStep from "./DetailsStep";
import {
  getFirstLiveValidationError,
  getStepDisplayValidationError,
  getBuiltInFieldValidationError,
  getBuiltInListValidationError,
  getCustomFieldValidationError,
} from "./validation";
import { useTranslation } from "@/i18n/LanguageContext";

function wizardReducer(state: WizardState, action: WizardAction): WizardState {

  switch (action.type) {
    case "SET_STEP":
      return { ...state, step: action.step };
    case "SET_VALUE":
      return { ...state, values: { ...state.values, [action.key]: action.value } };
    case "SET_SMURF_TAGS":
      return { ...state, smurfTags: action.tags };
    case "SET_FLEX":
      return {
        ...state,
        isFlex: action.isFlex,
        ...(action.isFlex ? { primaryRole: "", subrole: "", additionalRoles: [] } : {}),
      };
    case "SET_PRIMARY_ROLE":
      return { ...state, primaryRole: action.role, isFlex: false };
    case "SET_SUBROLE":
      return { ...state, subrole: action.subrole };
    case "SET_ADDITIONAL_ROLES":
      return { ...state, additionalRoles: action.roles };
    case "INIT_VALUES":
      return { ...state, values: { ...state.values, ...action.values } };
    default:
      return state;
  }
}

const initialState: WizardState = {
  step: 0,
  values: {},
  smurfTags: [],
  isFlex: false,
  primaryRole: "",
  subrole: "",
  additionalRoles: [],
};

interface RegistrationWizardProps {
  workspaceId: number;
  tournamentId: number;
  tournamentName?: string;
  form: RegistrationForm;
  onClose: () => void;
}

export default function RegistrationWizard({
  workspaceId,
  tournamentId,
  tournamentName,
  form,
  onClose,
}: RegistrationWizardProps) {
  const { t } = useTranslation();
  const { user: authUser } = useAuthProfile();
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(wizardReducer, initialState);
  const [error, setError] = useState<string | null>(null);
  const [liveValidationErrors, setLiveValidationErrors] = useState<Record<string, string | null>>({});

  const isEnabled = (fieldKey: string) => form.built_in_fields?.[fieldKey]?.enabled !== false;
  const isRequired = (fieldKey: string) =>
    isEnabled(fieldKey) && form.built_in_fields?.[fieldKey]?.required === true;
  const getBuiltInConfig = (fieldKey: string) => form.built_in_fields?.[fieldKey];

  const STEPS = [
    { label: t("registration.wizard.steps.accounts") },
    { label: t("registration.wizard.steps.roles") },
    { label: t("registration.wizard.steps.details") },
  ];

  const PRIMARY_ROLE_REQUIRED_ERROR = t("registration.wizard.validation.primaryRoleRequired");
  const ADDITIONAL_ROLES_REQUIRED_ERROR = t("registration.wizard.validation.fallbackRoleRequired");

  const userQuery = useQuery({
    queryKey: ["user-profile-full", authUser?.username],
    queryFn: () => userService.getUserByName(authUser!.username),
    enabled: !!authUser?.username,
    staleTime: 60_000,
  });

  const linkedUser: User | undefined = userQuery.data;
  const battleTagSuggestions = linkedUser?.battle_tag?.map((bt) => bt.battle_tag) ?? [];
  const discordSuggestions = linkedUser?.discord?.map((d) => d.name) ?? [];
  const twitchSuggestions = linkedUser?.twitch?.map((t) => t.name) ?? [];

  useEffect(() => {
    if (!linkedUser) return;
    const init: Record<string, string> = {};
    const bts = linkedUser.battle_tag?.map((bt) => bt.battle_tag) ?? [];
    const dcs = linkedUser.discord?.map((d) => d.name) ?? [];
    const tws = linkedUser.twitch?.map((t) => t.name) ?? [];
    if (isEnabled("battle_tag") && bts.length > 0) init.battle_tag = bts[0];
    if (isEnabled("discord_nick") && dcs.length > 0) init.discord_nick = dcs[0];
    if (isEnabled("twitch_nick") && tws.length > 0) init.twitch_nick = tws[0];
    dispatch({ type: "INIT_VALUES", values: init });
  }, [linkedUser]);

  const buildRolesPayload = (): { role: string; subrole?: string; is_primary: boolean }[] => {
    if (state.isFlex) {
      return ROLES.map((r) => ({ role: r.code, is_primary: true }));
    }
    const roles: { role: string; subrole?: string; is_primary: boolean }[] = [];
    if (state.primaryRole) {
      roles.push({
        role: state.primaryRole,
        ...(state.subrole ? { subrole: state.subrole } : {}),
        is_primary: true,
      });
    }
    for (const ar of state.additionalRoles) {
      roles.push({
        role: ar.code,
        ...(ar.subrole ? { subrole: ar.subrole } : {}),
        is_primary: false,
      });
    }
    return roles;
  };

  const mutation = useMutation({
    mutationFn: () => {
      const rolesPayload = buildRolesPayload();
      const input: RegistrationCreateInput = {
        battle_tag: isEnabled("battle_tag") ? (state.values.battle_tag || undefined) : undefined,
        smurf_tags: isEnabled("smurf_tags") && state.smurfTags.length > 0 ? state.smurfTags : undefined,
        discord_nick: isEnabled("discord_nick") ? (state.values.discord_nick || undefined) : undefined,
        twitch_nick: isEnabled("twitch_nick") ? (state.values.twitch_nick || undefined) : undefined,
        roles: rolesPayload.length > 0 ? rolesPayload : undefined,
        stream_pov: isEnabled("stream_pov") ? state.values.stream_pov === "true" : undefined,
        notes: isEnabled("notes") ? (state.values.notes || undefined) : undefined,
        custom_fields: Object.fromEntries(
          form.custom_fields
            .map((f) => [
              f.key,
              f.type === "checkbox"
                ? (state.values[f.key] === "true" ? "true" : "false")
                : (state.values[f.key] ?? ""),
            ])
            .filter(([, v]) => v !== ""),
        ),
      };
      return registrationService.register(tournamentId, input);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["registration", workspaceId, tournamentId] });
      await queryClient.invalidateQueries({
        queryKey: ["registrations-list", workspaceId, tournamentId],
      });
      onClose();
    },
    onError: (err: Error) => setError(err.message),
  });

  const isLastStep = state.step === STEPS.length - 1;

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
        ...form.custom_fields.map((field) => field.key),
      ];
    }

    return [];
  };

  const validateCurrentStep = (): string | null => {
    if (state.step === 0) {
      if (isRequired("battle_tag") && !state.values.battle_tag?.trim()) {
        return t("registration.wizard.validation.battleTagRequired");
      }
      if (isRequired("smurf_tags") && state.smurfTags.length === 0) {
        return t("registration.wizard.validation.smurfTagsRequired");
      }
      if (isRequired("discord_nick") && !state.values.discord_nick?.trim()) {
        return t("registration.wizard.validation.discordRequired");
      }
      if (isRequired("twitch_nick") && !state.values.twitch_nick?.trim()) {
        return t("registration.wizard.validation.twitchRequired");
      }
      return (
        (isEnabled("battle_tag") ? getBuiltInFieldValidationError(
          "battle_tag",
          state.values.battle_tag ?? "",
          getBuiltInConfig("battle_tag"),
          t,
        ) : null)
        ?? (isEnabled("smurf_tags") ? getBuiltInListValidationError(
          "smurf_tags",
          state.smurfTags,
          getBuiltInConfig("smurf_tags"),
          t,
        ) : null)
        ?? (isEnabled("discord_nick") ? getBuiltInFieldValidationError(
          "discord_nick",
          state.values.discord_nick ?? "",
          getBuiltInConfig("discord_nick"),
          t,
        ) : null)
        ?? (isEnabled("twitch_nick") ? getBuiltInFieldValidationError(
          "twitch_nick",
          state.values.twitch_nick ?? "",
          getBuiltInConfig("twitch_nick"),
          t,
        ) : null)
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
      return null;
    }

    if (state.step === 2) {
      if (isRequired("notes") && !state.values.notes?.trim()) {
        return t("registration.wizard.validation.notesRequired");
      }
      const notesValidationError = getBuiltInFieldValidationError(
        "notes",
        state.values.notes ?? "",
        getBuiltInConfig("notes"),
        t,
      );
      if (notesValidationError) {
        return notesValidationError;
      }

      for (const field of form.custom_fields) {
        const rawValue = state.values[field.key] ?? "";
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

    return null;
  };

  const currentStepLiveValidationError = getFirstLiveValidationError(
    liveValidationErrors,
    getCurrentStepLiveValidationFieldKeys(),
  );
  const currentStepBaseValidationError = validateCurrentStep();
  const currentStepValidationError = currentStepLiveValidationError ?? currentStepBaseValidationError;
  const currentStepDisplayValidationError = getStepDisplayValidationError(
    currentStepLiveValidationError,
    currentStepBaseValidationError,
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
    currentStepDisplayValidationError === roleStepPrimaryError
    || currentStepDisplayValidationError === roleStepSecondaryError
      ? null
      : currentStepDisplayValidationError;

  const handleNext = () => {
    if (currentStepValidationError) {
      return;
    }

    if (isLastStep) {
      mutation.mutate();
    } else {
      dispatch({ type: "SET_STEP", step: state.step + 1 });
    }
  };

  const handleBack = () => {
    setError(null);
    dispatch({ type: "SET_STEP", step: state.step - 1 });
  };

  const handleValueUpdate = (key: string, value: string) => {
    setError(null);
    dispatch({ type: "SET_VALUE", key, value });
  };

  const handleSmurfTagsChange = (tags: string[]) => {
    setError(null);
    dispatch({ type: "SET_SMURF_TAGS", tags });
  };

  const handleBuiltInValidationChange = (fieldKey: string, nextError: string | null) => {
    setLiveValidationErrors((prev) => {
      if (prev[fieldKey] === nextError) {
        return prev;
      }
      return {
        ...prev,
        [fieldKey]: nextError,
      };
    });
  };

  const handleFlexChange = (isFlex: boolean) => {
    setError(null);
    dispatch({ type: "SET_FLEX", isFlex });
  };

  const handlePrimaryRoleChange = (role: string) => {
    setError(null);
    dispatch({ type: "SET_PRIMARY_ROLE", role });
  };

  const handleSubroleChange = (subrole: string) => {
    setError(null);
    dispatch({ type: "SET_SUBROLE", subrole });
  };

  const handleAdditionalRolesChange = (roles: AdditionalRole[]) => {
    setError(null);
    dispatch({ type: "SET_ADDITIONAL_ROLES", roles });
  };

  return (
    <div className="flex flex-col gap-5 sm:min-h-[560px] lg:min-h-[640px]">
      <div>
        <h2 className="text-lg font-semibold text-white">
          {tournamentName ? t("registration.wizard.titleFor", { name: tournamentName }) : t("registration.wizard.title")}
        </h2>
        <p className="mt-1 text-sm text-white/50">
          {state.step === 0 && t("registration.wizard.step1Desc")}
          {state.step === 1 && t("registration.wizard.step2Desc")}
          {state.step === 2 && t("registration.wizard.step3Desc")}
        </p>
      </div>

      <StepIndicator steps={STEPS} current={state.step} />

      <div className="flex-1">
        {state.step === 0 && (
          <AccountStep
            values={state.values}
            onUpdate={handleValueUpdate}
            smurfTags={state.smurfTags}
            onSmurfTagsChange={handleSmurfTagsChange}
            onBuiltInValidationChange={handleBuiltInValidationChange}
            form={form}
            battleTagSuggestions={battleTagSuggestions}
            discordSuggestions={discordSuggestions}
            twitchSuggestions={twitchSuggestions}
          />
        )}
        {state.step === 1 && (
          <RoleStep
            isFlex={state.isFlex}
            primaryRole={state.primaryRole}
            subrole={state.subrole}
            additionalRoles={state.additionalRoles}
            onSetFlex={handleFlexChange}
            onSetPrimaryRole={handlePrimaryRoleChange}
            onSetSubrole={handleSubroleChange}
            onSetAdditionalRoles={handleAdditionalRolesChange}
            primaryRoleError={roleStepPrimaryError}
            secondaryRolesError={roleStepSecondaryError}
            form={form}
          />
        )}
        {state.step === 2 && (
          <DetailsStep
            values={state.values}
            onUpdate={handleValueUpdate}
            onFieldValidationChange={handleBuiltInValidationChange}
            form={form}
          />
        )}
      </div>

      {(error || footerValidationError) && (
        <p className="text-sm text-red-400">{error ?? footerValidationError}</p>
      )}

      <div className="flex items-center justify-between border-t border-white/8 pt-4">
        {state.step > 0 ? (
          <button
            type="button"
            onClick={handleBack}
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-sm font-medium text-white/60 transition-colors hover:bg-white/4"
          >
            <ArrowLeft className="size-3.5" />
            {t("common.back")}
          </button>
        ) : (
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/10 px-3 py-2 text-sm font-medium text-white/60 transition-colors hover:bg-white/4"
          >
            {t("common.cancel")}
          </button>
        )}

        <button
          type="button"
          onClick={handleNext}
          disabled={mutation.isPending || Boolean(currentStepValidationError)}
          className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {mutation.isPending && <Loader2 className="size-4 animate-spin" />}
          {isLastStep ? (
            t("common.submit")
          ) : (
            <>
              {t("common.next")}
              <ArrowRight className="size-3.5" />
            </>
          )}
        </button>
      </div>
    </div>
  );
}

