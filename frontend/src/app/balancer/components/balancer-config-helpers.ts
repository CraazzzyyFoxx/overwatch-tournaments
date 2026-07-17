import {
  SUPPORTED_BALANCER_ALGORITHMS,
  SUPPORTED_BALANCER_CONFIG_KEYS,
  type BalancerConfig,
  type BalancerConfigResponse,
} from "@/types/balancer.types";

export const CUSTOM_PRESET = "CUSTOM";

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

const NUMERIC_CONFIG_KEYS = new Set<string>([
  "population_size",
  "generation_count",
  "mutation_rate",
  "mutation_strength",
  "average_mmr_balance_weight",
  "team_total_balance_weight",
  "max_team_gap_weight",
  "role_discomfort_weight",
  "intra_team_variance_weight",
  "max_role_discomfort_weight",
  "role_line_balance_weight",
  "role_spread_weight",
  "intra_team_std_weight",
  "internal_role_spread_weight",
  "sub_role_collision_weight",
  "tank_impact_weight",
  "dps_impact_weight",
  "support_impact_weight",
  "tank_gap_weight",
  "tank_std_weight",
  "effective_total_std_weight",
  "convergence_patience",
  "convergence_epsilon",
  "mutation_rate_min",
  "mutation_rate_max",
  "island_count",
  "polish_max_passes",
  "greedy_seed_count",
  "stagnation_kick_patience",
  "crossover_rate",
  "max_result_variants",
  "rank_comfort_tilt",
]);

const SUPPORTED_CONFIG_KEY_SET = new Set<string>(SUPPORTED_BALANCER_CONFIG_KEYS);
const SUPPORTED_BALANCER_ALGORITHM_SET = new Set<string>(SUPPORTED_BALANCER_ALGORITHMS);

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

export function sanitizeBalancerConfig(config: BalancerConfig | null | undefined): BalancerConfig {
  if (!config) {
    return {};
  }

  const entries = Object.entries(config).flatMap(([key, value]) => {
    if (!SUPPORTED_CONFIG_KEY_SET.has(key)) {
      return [];
    }

    if (value === undefined || value === null) {
      return [];
    }

    if (typeof value === "string") {
      const trimmedValue = value.trim();
      if (trimmedValue === "") {
        return [];
      }

      if (key === "algorithm") {
        return SUPPORTED_BALANCER_ALGORITHM_SET.has(trimmedValue) ? [[key, trimmedValue]] : [];
      }

      if (NUMERIC_CONFIG_KEYS.has(key)) {
        const numericValue = Number(trimmedValue);
        return Number.isFinite(numericValue) ? [[key, numericValue]] : [];
      }
    }

    if (key === "algorithm") {
      return typeof value === "string" && SUPPORTED_BALANCER_ALGORITHM_SET.has(value)
        ? [[key, value]]
        : [];
    }

    return [[key, value]];
  });

  return Object.fromEntries(entries) as BalancerConfig;
}

export function serializeBalancerConfig(config: BalancerConfig | null | undefined): string {
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
