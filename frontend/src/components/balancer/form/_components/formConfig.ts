import type {
  AdminCustomFieldDef,
  BuiltInFieldConfig,
  FieldValidationConfig,
} from "@/types/balancer-admin.types";

// ---------------------------------------------------------------------------
// Built-in field definitions
// ---------------------------------------------------------------------------

export interface BuiltInFieldDef {
  key: string;
  /** UI label and description live in `registrationFormAdmin.builtInFields.defs.<key>`. */
  defaultEnabled: boolean;
  defaultRequired: boolean;
  /** Role fields whose sub-roles are configured in the dedicated Subroles tab. */
  hasSubroles?: boolean;
  supportsValidation?: boolean;
  defaultValidation?: FieldValidationConfig;
  /** Whether the "Required" toggle applies (default true). */
  supportsRequired?: boolean;
  /** `top_heroes`: shows a numeric "max heroes" input (default 5). */
  supportsMaxHeroes?: boolean;
  /** Identity fields: shows a "Verified" toggle (require an OAuth-verified account). */
  supportsVerified?: boolean;
  /** `flex_role`: shows an optional/forced mode select instead of "Required". */
  supportsMode?: boolean;
}

const DEFAULT_BATTLE_TAG_REGEX = String.raw`([^#]{2,12}#[0-9]{4,})`;
const DEFAULT_DISCORD_REGEX = String.raw`^[a-z0-9_.]{2,32}$`;
const DEFAULT_TWITCH_REGEX = String.raw`^[a-zA-Z0-9_]{4,25}$`;
const DEFAULT_BOOSTY_REGEX = String.raw`^[^#]{2,50}$`;
const DEFAULT_URL_REGEX = String.raw`^https?://.+$`;
const DEFAULT_NUMBER_REGEX = String.raw`^-?\d+(?:[.,]\d+)?$`;

export const BUILT_IN_FIELDS: BuiltInFieldDef[] = [
  {
    key: "battle_tag",
    defaultEnabled: true,
    defaultRequired: true,
    supportsValidation: true,
    supportsVerified: true,
    defaultValidation: {
      regex: DEFAULT_BATTLE_TAG_REGEX,
      error_message: "BattleTag must match Player#1234.",
    },
  },
  {
    key: "smurf_tags",
    defaultEnabled: false,
    defaultRequired: false,
    supportsValidation: true,
    defaultValidation: {
      regex: DEFAULT_BATTLE_TAG_REGEX,
      error_message: "Each smurf BattleTag must match Player#1234.",
    },
  },
  {
    key: "discord_nick",
    defaultEnabled: true,
    defaultRequired: false,
    supportsValidation: true,
    supportsVerified: true,
    defaultValidation: {
      regex: DEFAULT_DISCORD_REGEX,
      error_message: "Discord username must contain 2-32 lowercase letters, digits, underscores, or dots.",
    },
  },
  {
    key: "twitch_nick",
    defaultEnabled: true,
    defaultRequired: false,
    supportsValidation: true,
    supportsVerified: true,
    defaultValidation: {
      regex: DEFAULT_TWITCH_REGEX,
      error_message: "Twitch channel name must contain 4-25 letters, digits, or underscores.",
    },
  },
  {
    key: "primary_role",
    defaultEnabled: true,
    defaultRequired: false,
    hasSubroles: true,
  },
  {
    key: "additional_roles",
    defaultEnabled: false,
    defaultRequired: false,
    hasSubroles: true,
  },
  {
    key: "flex_role",
    defaultEnabled: true,
    defaultRequired: false,
    supportsRequired: false,
    supportsMode: true,
  },
  {
    key: "boosty_nick",
    defaultEnabled: false,
    defaultRequired: false,
    supportsValidation: true,
    // Deliberately NOT verifiable. Boosty has no third-party OAuth and neither
    // viable path (Discord roles, challenge code) reveals the handle, so the
    // nickname stays self-declared. Offering a "Verified" toggle here would
    // promise a guarantee that cannot be delivered — the trust lives in the
    // subscription entitlement shown beside the field, not in the handle.
    supportsVerified: false,
    defaultValidation: {
      regex: DEFAULT_BOOSTY_REGEX,
      error_message: "Boosty nickname must be 2-50 characters and cannot contain '#'.",
    },
  },
  {
    key: "top_heroes",
    defaultEnabled: false,
    defaultRequired: false,
    supportsMaxHeroes: true,
  },
  { key: "stream_pov", defaultEnabled: false, defaultRequired: false },
  {
    key: "notes",
    defaultEnabled: true,
    defaultRequired: false,
    supportsValidation: true,
  },
];

/** Role fields whose sub-role selection is edited in the Subroles tab. */
export const ROLE_FIELD_KEYS = ["primary_role", "additional_roles"] as const;

/** Labels live in `registrationFormAdmin.customFields.types.<value>`. */
export const FIELD_TYPE_OPTIONS = [
  { value: "text" },
  { value: "number" },
  { value: "url" },
  { value: "select" },
  { value: "checkbox" },
] as const;

// ---------------------------------------------------------------------------
// Validation helpers
// ---------------------------------------------------------------------------

export function normalizeValidation(
  validation?: FieldValidationConfig | null,
): FieldValidationConfig | null {
  const regex = validation?.regex?.trim() || null;
  const error_message = validation?.error_message?.trim() || null;
  if (!regex && !error_message) {
    return null;
  }
  return {
    ...(regex ? { regex } : {}),
    ...(error_message ? { error_message } : {}),
  };
}

function mergeDefaultValidation(
  validation?: FieldValidationConfig | null,
  defaultValidation?: FieldValidationConfig | null,
): FieldValidationConfig | null {
  const normalized = normalizeValidation(validation);
  const normalizedDefault = normalizeValidation(defaultValidation);
  if (!normalizedDefault) {
    return normalized;
  }

  return normalizeValidation({
    regex: normalized?.regex ?? normalizedDefault.regex ?? null,
    error_message: normalized?.error_message ?? normalizedDefault.error_message ?? null,
  });
}

export function getCustomFieldDefaultValidation(
  type: AdminCustomFieldDef["type"],
): FieldValidationConfig | null {
  switch (type) {
    case "url":
      return {
        regex: DEFAULT_URL_REGEX,
        error_message: "Value must start with http:// or https://.",
      };
    case "number":
      return {
        regex: DEFAULT_NUMBER_REGEX,
        error_message: "Enter a valid number.",
      };
    default:
      return null;
  }
}

export function hydrateCustomField(field: AdminCustomFieldDef): AdminCustomFieldDef {
  return {
    ...field,
    validation: mergeDefaultValidation(
      field.validation,
      getCustomFieldDefaultValidation(field.type),
    ),
  };
}

export function supportsCustomFieldValidation(type: AdminCustomFieldDef["type"]): boolean {
  return type === "text" || type === "number" || type === "url";
}

// ---------------------------------------------------------------------------
// Built-in config hydration
// ---------------------------------------------------------------------------

export function getBuiltInConfig(
  saved: Record<string, BuiltInFieldConfig>,
): Record<string, BuiltInFieldConfig> {
  const result: Record<string, BuiltInFieldConfig> = {};
  for (const field of BUILT_IN_FIELDS) {
    const existing = saved[field.key];
    const next: BuiltInFieldConfig = existing
      ? { ...existing }
      : { enabled: field.defaultEnabled, required: field.defaultRequired };
    // Sub-role options are data-driven from the workspace catalog; preserve any
    // explicit per-tournament selection but do not inject hardcoded defaults.
    if (next.subroles) {
      next.subroles = { ...next.subroles };
    }
    next.validation = mergeDefaultValidation(next.validation, field.defaultValidation);
    result[field.key] = next;
  }
  return result;
}

