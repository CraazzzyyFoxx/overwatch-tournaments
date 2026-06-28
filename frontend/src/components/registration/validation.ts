import type {
  BuiltInFieldConfig,
  CustomFieldDefinition,
  FieldValidationConfig,
} from "@/types/registration.types";
import type { SocialAccount, SocialProvider } from "@/types/user.types";

const BUILT_IN_LABELS: Record<string, string> = {
  battle_tag: "BattleTag",
  smurf_tags: "Smurf Accounts",
  discord_nick: "Discord",
  twitch_nick: "Twitch",
  notes: "Notes",
};

/**
 * Identity registration fields that can require an OAuth-verified social
 * account, mapped to the canonical provider their handle must match. Mirrors
 * the backend `VERIFIED_FIELD_PROVIDERS` (tournament-service validation.py).
 */
export const VERIFIED_FIELD_PROVIDERS: Record<string, SocialProvider> = {
  battle_tag: "battlenet",
  discord_nick: "discord",
  twitch_nick: "twitch",
};

const BUILT_IN_LABEL_KEYS: Record<string, string> = {
  battle_tag: "registration.accounts.battleTag",
  smurf_tags: "registration.accounts.smurfs",
  discord_nick: "registration.accounts.discord",
  twitch_nick: "registration.accounts.twitch",
  notes: "registration.details.notes",
};

const TEXT_VALIDATION_FIELD_TYPES = new Set<CustomFieldDefinition["type"]>(["text", "number", "url"]);
const DEFAULT_BATTLE_TAG_REGEX = String.raw`([\w0-9]{2,12}#[0-9]{4,})`;
const DEFAULT_BATTLE_TAG_VALIDATION: FieldValidationConfig = {
  regex: DEFAULT_BATTLE_TAG_REGEX,
};

function normalizeBattleTag(value: string): string {
  return value.trim().replace(/\s*#\s*/g, "#").replace(/\s+/g, "");
}

export function normalizeBuiltInFieldValue(fieldKey: string, value: string): string {
  const trimmed = value.trim();
  if (fieldKey === "battle_tag" || fieldKey === "smurf_tags") {
    return normalizeBattleTag(trimmed);
  }
  return trimmed;
}

function buildRegex(validation?: FieldValidationConfig | null): RegExp | null {
  const pattern = validation?.regex?.trim();
  if (!pattern) {
    return null;
  }

  try {
    return new RegExp(`^(?:${pattern})$`);
  } catch {
    return null;
  }
}

function resolveBuiltInValidation(
  fieldKey: string,
  validation?: FieldValidationConfig | null,
): FieldValidationConfig | null {
  if (validation?.regex?.trim()) {
    return validation;
  }
  if (fieldKey === "battle_tag") {
    return {
      ...DEFAULT_BATTLE_TAG_VALIDATION,
      ...(validation?.error_message?.trim() ? { error_message: validation.error_message } : {}),
    };
  }
  return validation ?? null;
}

function getErrorMessage(
  validation: FieldValidationConfig | null | undefined,
  label: string,
  t?: (key: string, variables?: Record<string, string | number>) => string,
): string {
  return validation?.error_message?.trim() || (t ? t("registration.wizard.validation.invalidFormat", { label }) : `${label} format is invalid.`);
}

export function getBuiltInFieldValidationError(
  fieldKey: string,
  value: string,
  config?: BuiltInFieldConfig,
  t?: (key: string, variables?: Record<string, string | number>) => string,
): string | null {
  return getBuiltInValueValidationError(fieldKey, value, config, t);
}

export function getBuiltInValueValidationError(
  fieldKey: string,
  value: string,
  config?: BuiltInFieldConfig,
  t?: (key: string, variables?: Record<string, string | number>) => string,
): string | null {
  const validation = resolveBuiltInValidation(fieldKey, config?.validation);
  const regex = buildRegex(validation);
  const candidate = normalizeBuiltInFieldValue(fieldKey, value);
  if (!regex || !candidate) {
    return null;
  }
  if (regex.test(candidate)) {
    return null;
  }

  const labelKey = BUILT_IN_LABEL_KEYS[fieldKey];
  const localizedLabel = (t && labelKey) ? t(labelKey) : (BUILT_IN_LABELS[fieldKey] ?? fieldKey);
  return getErrorMessage(validation, localizedLabel, t);
}

export function getBuiltInListValidationError(
  fieldKey: string,
  values: string[],
  config?: BuiltInFieldConfig,
  t?: (key: string, variables?: Record<string, string | number>) => string,
): string | null {
  if (values.length === 0) {
    return null;
  }

  for (const value of values) {
    const error = getBuiltInValueValidationError(fieldKey, value, config, t);
    if (error) {
      return error;
    }
  }

  return null;
}

/** Canonical handle form for matching against a verified account. Mirrors the
 *  backend `normalize_social_handle`: all providers are casefolded; BattleTags
 *  additionally have `#`-separator spacing and whitespace stripped. */
function normalizeSocialHandle(provider: SocialProvider, value: string): string {
  let text = value.trim();
  if (provider === "battlenet") {
    text = text.replace(/\s*#\s*/g, "#").replace(/\s+/g, "");
  }
  return text.toLowerCase();
}

/**
 * Validate a `require_verified` identity field against the registrant's
 * OAuth-verified social accounts. Returns a (localized) error when the field is
 * gated and the player has no verified account for the provider, or the value
 * doesn't match one. Returns null when the field isn't gated.
 */
export function getVerifiedFieldError(
  fieldKey: string,
  value: string,
  config: BuiltInFieldConfig | undefined,
  verifiedAccounts: readonly SocialAccount[],
  t?: (key: string, variables?: Record<string, string | number>) => string,
): string | null {
  if (!config || config.enabled === false || !config.require_verified) {
    return null;
  }
  const provider = VERIFIED_FIELD_PROVIDERS[fieldKey];
  if (!provider) {
    return null;
  }

  const labelKey = BUILT_IN_LABEL_KEYS[fieldKey];
  const label = (t && labelKey) ? t(labelKey) : (BUILT_IN_LABELS[fieldKey] ?? fieldKey);

  const candidates = verifiedAccounts.filter((a) => a.provider === provider && a.is_verified);
  if (candidates.length === 0) {
    return t
      ? t("registration.wizard.validation.verifiedNoAccount", { label })
      : `Link a verified ${label} account via OAuth to register.`;
  }

  if (!value.trim()) {
    return t
      ? t("registration.wizard.validation.verifiedRequired", { label })
      : `Select your verified ${label} account.`;
  }

  const target = normalizeSocialHandle(provider, value);
  const matched = candidates.some((a) => normalizeSocialHandle(provider, a.username) === target);
  if (!matched) {
    return t
      ? t("registration.wizard.validation.verifiedMismatch", { label })
      : `${label} must match an OAuth-verified account on your profile.`;
  }

  return null;
}

export function supportsCustomFieldValidation(
  field: Pick<CustomFieldDefinition, "type">,
): boolean {
  return TEXT_VALIDATION_FIELD_TYPES.has(field.type);
}

export function getCustomFieldValidationError(
  field: CustomFieldDefinition,
  value: string,
  t?: (key: string, variables?: Record<string, string | number>) => string,
): string | null {
  if (!supportsCustomFieldValidation(field)) {
    return null;
  }

  const regex = buildRegex(field.validation);
  const rawValue = value.trim();
  if (!regex || !rawValue) {
    return null;
  }

  if (regex.test(rawValue)) {
    return null;
  }

  return getErrorMessage(field.validation, field.label, t);
}


export function getFirstLiveValidationError(
  fieldErrors: Record<string, string | null | undefined>,
  fieldKeys: string[],
): string | null {
  for (const fieldKey of fieldKeys) {
    const error = fieldErrors[fieldKey];
    if (error) {
      return error;
    }
  }

  return null;
}

export function getStepDisplayValidationError(
  liveValidationError: string | null,
  stepValidationError: string | null,
): string | null {
  if (liveValidationError) {
    return null;
  }

  return stepValidationError;
}
