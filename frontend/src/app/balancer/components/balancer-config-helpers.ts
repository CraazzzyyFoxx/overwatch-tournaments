import type { BalancerConfig, BalancerConfigResponse } from "@/types/balancer.types";

export const CUSTOM_PRESET = "CUSTOM";

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

function sortJsonValue(value: unknown): JsonValue {
  if (Array.isArray(value)) {
    return value.map(sortJsonValue);
  }

  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, nestedValue]) => nestedValue !== undefined && nestedValue !== null)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, nestedValue]) => [key, sortJsonValue(nestedValue)])
    );
  }

  if (
    value === null ||
    typeof value === "boolean" ||
    typeof value === "number" ||
    typeof value === "string"
  ) {
    return value;
  }

  return null;
}

/** Drops empty values and turns a numeric input's raw string into a number.
 *
 * There is deliberately no key allowlist here: which knobs exist is the
 * backend's answer (`BalancerConfigResponse.fields`), and anything unknown that
 * slips through is dropped server-side by `normalize_config_payload`. The
 * allowlist this file used to carry was a third copy of that list and had
 * drifted from it in both directions. Every knob is numeric or boolean, so a
 * string here can only be a number input mid-edit.
 */
export function sanitizeBalancerConfig(config: BalancerConfig | null | undefined): BalancerConfig {
  if (!config) {
    return {};
  }

  const entries = Object.entries(config).flatMap(([key, value]) => {
    if (value === undefined || value === null) {
      return [];
    }

    if (typeof value === "string") {
      const trimmed = value.trim();
      const numeric = Number(trimmed);
      return trimmed !== "" && Number.isFinite(numeric) ? [[key, numeric]] : [];
    }

    return [[key, value]];
  });

  return Object.fromEntries(entries) as BalancerConfig;
}

function serializeBalancerConfig(config: BalancerConfig | null | undefined): string {
  return JSON.stringify(sortJsonValue(sanitizeBalancerConfig(config)));
}

export function areBalancerConfigsEqual(
  left: BalancerConfig | null | undefined,
  right: BalancerConfig | null | undefined
): boolean {
  return serializeBalancerConfig(left) === serializeBalancerConfig(right);
}

export function resolveInitialBalancerConfig(
  configData: BalancerConfigResponse,
  tournamentConfig: Record<string, unknown> | null | undefined
): BalancerConfig {
  return sanitizeBalancerConfig(
    (tournamentConfig as BalancerConfig | null | undefined) ?? configData.defaults
  );
}

export function findMatchingPreset(
  config: BalancerConfig,
  presets: Record<string, BalancerConfig>
): string | null {
  for (const [presetName, presetConfig] of Object.entries(presets)) {
    if (areBalancerConfigsEqual(config, presetConfig)) {
      return presetName;
    }
  }

  return null;
}

export function getRunConfig(
  draftConfig: BalancerConfig,
  configData: BalancerConfigResponse | undefined,
  selectedPreset: string
): BalancerConfig | undefined {
  const sanitizedDraft = sanitizeBalancerConfig(draftConfig);

  if (Object.keys(sanitizedDraft).length > 0) {
    return sanitizedDraft;
  }

  if (!configData) {
    return undefined;
  }

  if (selectedPreset !== CUSTOM_PRESET && configData.presets[selectedPreset]) {
    return sanitizeBalancerConfig(configData.presets[selectedPreset]);
  }

  return sanitizeBalancerConfig(configData.defaults);
}
