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
  label: string;
  description: string;
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
}

export const DEFAULT_BATTLE_TAG_REGEX = String.raw`([\w0-9]{2,12}#[0-9]{4,})`;
export const DEFAULT_DISCORD_REGEX = String.raw`^[a-z0-9_.]{2,32}$`;
export const DEFAULT_TWITCH_REGEX = String.raw`^[a-z0-9_]{4,25}$`;
export const DEFAULT_URL_REGEX = String.raw`^https?://.+$`;
export const DEFAULT_NUMBER_REGEX = String.raw`^-?\d+(?:[.,]\d+)?$`;

export const BUILT_IN_FIELDS: BuiltInFieldDef[] = [
  {
    key: "battle_tag",
    label: "BattleTag",
    description: "Battle.net tag (e.g. Player#1234)",
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
    label: "Smurf Accounts",
    description: "Additional BattleTag accounts (smurfs)",
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
    label: "Discord",
    description: "Discord username",
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
    label: "Twitch",
    description: "Twitch channel name",
    defaultEnabled: true,
    defaultRequired: false,
    supportsValidation: true,
    supportsVerified: true,
    defaultValidation: {
      regex: DEFAULT_TWITCH_REGEX,
      error_message: "Twitch channel name must contain 4-25 lowercase letters, digits, or underscores.",
    },
  },
  {
    key: "primary_role",
    label: "Primary Role",
    description: "Main role (tank/dps/support) with subrole selection",
    defaultEnabled: true,
    defaultRequired: false,
    hasSubroles: true,
  },
  {
    key: "additional_roles",
    label: "Additional Roles",
    description: "Secondary roles the player can fill",
    defaultEnabled: false,
    defaultRequired: false,
    hasSubroles: true,
  },
  {
    key: "flex_role",
    label: "Flex Role",
    description: "Let players register as Flex (all roles, equal priority)",
    defaultEnabled: true,
    defaultRequired: false,
    supportsRequired: false,
  },
  {
    key: "top_heroes",
    label: "Top Heroes",
    description: "Let players pick their best heroes per role",
    defaultEnabled: false,
    defaultRequired: false,
    supportsMaxHeroes: true,
  },
  { key: "stream_pov", label: "Stream POV", description: "Player will stream their POV", defaultEnabled: false, defaultRequired: false },
  {
    key: "notes",
    label: "Notes",
    description: "Free-text notes from the player",
    defaultEnabled: true,
    defaultRequired: false,
    supportsValidation: true,
  },
];

/** Role fields whose sub-role selection is edited in the Subroles tab. */
export const ROLE_FIELD_KEYS = ["primary_role", "additional_roles"] as const;

export const FIELD_TYPE_OPTIONS = [
  { value: "text", label: "Text" },
  { value: "number", label: "Number" },
  { value: "url", label: "URL" },
  { value: "select", label: "Select" },
  { value: "checkbox", label: "Checkbox" },
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

export function mergeDefaultValidation(
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

// ---------------------------------------------------------------------------
// Custom field keys (stable, unique, decoupled from the label)
// ---------------------------------------------------------------------------

function slugifyKey(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

/** Generate a stable unique key for a new custom field, never derived again. */
export function makeUniqueCustomFieldKey(
  label: string,
  existingKeys: Iterable<string>,
): string {
  const taken = new Set(existingKeys);
  const base = slugifyKey(label) || "field";
  if (!taken.has(base)) {
    return base;
  }
  let index = 2;
  while (taken.has(`${base}_${index}`)) {
    index += 1;
  }
  return `${base}_${index}`;
}
