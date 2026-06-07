import type {
  MappingCatalog,
  MappingFieldError,
  MappingTargetDef,
  MappingTargetGroup,
  MappingTargetState,
  ValueMapRow,
  ValueMappingState,
} from "@/types/balancer-admin.types";

// ---------------------------------------------------------------------------
// Shared display / error helpers
// ---------------------------------------------------------------------------

/** Render a parsed-field value (string/number/bool/object) as display text. */
export function formatParsedValue(value: unknown): string {
  if (value == null) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/** Resolve a catalog target key from the nested parsed-fields response. */
export function parsedTargetValue(parsedFields: Record<string, unknown>, targetKey: string): unknown {
  const path =
    targetKey.endsWith(".division_input")
      ? targetKey.replace(/\.division_input$/, ".rank_value")
      : targetKey;
  let value: unknown = parsedFields;
  for (const part of path.split(".")) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return undefined;
    }
    value = (value as Record<string, unknown>)[part];
  }
  return value;
}

/**
 * Dedupe header names the same way the backend does: the first occurrence keeps
 * its name, later duplicates get a `__N` suffix.
 */
export function dedupeHeaders(headers: string[]): string[] {
  const seen = new Map<string, number>();
  return headers.map((header) => {
    const count = seen.get(header) ?? 0;
    seen.set(header, count + 1);
    return count === 0 ? header : `${header}__${count}`;
  });
}

/** Collapse a list of field errors into the first message per target key. */
export function toFieldErrors(errors: MappingFieldError[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const error of errors) {
    if (error.target && !result[error.target]) {
      result[error.target] = error.message;
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Group ordering / labels
// ---------------------------------------------------------------------------

export const GROUP_ORDER: MappingTargetGroup[] = ["identity", "profile", "roles", "custom_fields"];

export const GROUP_LABELS: Record<MappingTargetGroup, string> = {
  identity: "Identity",
  profile: "Profile",
  roles: "Roles",
  custom_fields: "Custom fields",
};

export const GROUP_DESCRIPTIONS: Record<MappingTargetGroup, string> = {
  identity: "Who the player is — battle tag, smurfs, and source record key.",
  profile: "Contact and stream details synced into the registration.",
  roles: "How roles, ranks, and sub-roles are read from the sheet.",
  custom_fields: "Extra registration-form fields populated from the sheet.",
};

// ---------------------------------------------------------------------------
// Roles sub-grouping (driven by target key prefixes)
// ---------------------------------------------------------------------------

export interface RoleSubgroup {
  id: string;
  label: string;
}

const ROLE_SUBGROUP_LABELS: Record<string, string> = {
  source_roles: "Declared roles",
  tank: "Tank",
  dps: "DPS",
  support: "Support",
};

const ROLE_SUBGROUP_ORDER = ["source_roles", "tank", "dps", "support", "other"] as const;

/** Resolve the sub-group id for a roles-group target from its key. */
export function roleSubgroupId(targetKey: string): string {
  if (targetKey.startsWith("source_roles")) {
    return "source_roles";
  }
  if (targetKey.startsWith("roles.")) {
    const role = targetKey.split(".")[1];
    if (role && ROLE_SUBGROUP_LABELS[role]) {
      return role;
    }
  }
  return "other";
}

export function roleSubgroupLabel(id: string): string {
  return ROLE_SUBGROUP_LABELS[id] ?? "Other";
}

/** Ordered, de-duplicated list of role sub-groups present in the targets. */
export function orderedRoleSubgroups(targets: MappingTargetDef[]): RoleSubgroup[] {
  const present = new Set(targets.map((target) => roleSubgroupId(target.key)));
  return ROLE_SUBGROUP_ORDER.filter((id) => present.has(id)).map((id) => ({
    id,
    label: roleSubgroupLabel(id),
  }));
}

/** Targets grouped by top-level group, preserving catalog order within a group. */
export function targetsByGroup(catalog: MappingCatalog): Record<MappingTargetGroup, MappingTargetDef[]> {
  const grouped: Record<MappingTargetGroup, MappingTargetDef[]> = {
    identity: [],
    profile: [],
    roles: [],
    custom_fields: [],
  };
  for (const target of catalog.targets) {
    grouped[target.group].push(target);
  }
  return grouped;
}

// ---------------------------------------------------------------------------
// JSON builders (state -> backend payload). Built only at save/preview time.
// ---------------------------------------------------------------------------

export type MappingTargetEntry =
  | { mode: "columns"; columns: string[]; parser?: string }
  | { mode: "constant"; value: string; parser?: string };

/**
 * `mapping_config_json` shape. Includes an index signature so it remains
 * assignable to the `Record<string, unknown>` payload field on the inputs.
 */
export type MappingConfigJson = {
  targets: Record<string, MappingTargetEntry>;
} & Record<string, unknown>;

/**
 * Serialize the per-target UI state into `mapping_config_json`.
 * Disabled targets are omitted entirely. Constant entries carry `{mode,value}`;
 * column entries carry `{mode,columns}`. The parser is included when set.
 */
export function buildMappingConfigJson(state: Record<string, MappingTargetState>): MappingConfigJson {
  const targets: Record<string, MappingTargetEntry> = {};

  for (const [key, target] of Object.entries(state)) {
    if (target.mode === "disabled") {
      continue;
    }

    const parser = target.parser?.trim() ? target.parser.trim() : undefined;

    if (target.mode === "constant") {
      targets[key] = {
        mode: "constant",
        value: target.value ?? "",
        ...(parser ? { parser } : {}),
      };
      continue;
    }

    const columns = target.columns.filter((column) => column.length > 0);
    if (columns.length === 0) {
      // No columns chosen yet — treat as not-configured rather than emitting an
      // empty mapping the backend would reject.
      continue;
    }
    targets[key] = {
      mode: "columns",
      columns,
      ...(parser ? { parser } : {}),
    };
  }

  return { targets };
}

/**
 * `value_mapping_json` shape. Includes an index signature so it remains
 * assignable to the `Record<string, unknown>` payload field on the inputs.
 */
export type ValueMappingJson = {
  booleans: Record<string, boolean>;
  roles: Record<string, string>;
  subroles: Record<string, string>;
  divisions: Record<string, number>;
} & Record<string, unknown>;

const TRUTHY = new Set(["true", "1", "yes", "y", "on"]);

function rowsToBooleans(rows: ValueMapRow[]): Record<string, boolean> {
  const result: Record<string, boolean> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (!key) {
      continue;
    }
    result[key] = TRUTHY.has(row.value.trim().toLowerCase());
  }
  return result;
}

function rowsToStrings(rows: ValueMapRow[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (!key) {
      continue;
    }
    result[key] = row.value.trim();
  }
  return result;
}

function rowsToNumbers(rows: ValueMapRow[]): Record<string, number> {
  const result: Record<string, number> = {};
  for (const row of rows) {
    const key = row.key.trim();
    const rawValue = row.value.trim();
    const value = Number(rawValue);
    if (!key || !rawValue || !Number.isFinite(value)) {
      continue;
    }
    result[key] = value;
  }
  return result;
}

/** Serialize the value-mapping editors into `value_mapping_json`. */
export function buildValueMappingJson(state: ValueMappingState): ValueMappingJson {
  return {
    booleans: rowsToBooleans(state.booleans),
    roles: rowsToStrings(state.roles),
    subroles: rowsToStrings(state.subroles),
    divisions: rowsToNumbers(state.divisions),
  };
}
