import {
  BalanceJobCreateResponse,
  BalanceJobEvent,
  BalanceJobResult,
  BalanceJobStatusResponse,
  BalancerConfig,
  BalancerConfigResponse,
  BalancerConfigField,
  SUPPORTED_BALANCER_ALGORITHMS,
  SUPPORTED_BALANCER_CONFIG_KEYS
} from "@/types/balancer.types";
import { apiFetch } from "@/lib/api-fetch";
import { getTokenFromCookies } from "@/lib/auth-tokens";

const BALANCER_STREAM_PREFIX = (
  process.env.NEXT_PUBLIC_BALANCER_API_URL || "http://localhost/api/balancer"
).replace(/\/$/, "");

const SUPPORTED_CONFIG_FIELD_TYPES = new Set([
  "boolean",
  "float",
  "integer",
  "role_mask",
  "select"
]);

type RawBalancerConfigField = Omit<BalancerConfigField, "key"> & {
  key: string;
};

type RawBalancerConfigResponse = Omit<BalancerConfigResponse, "defaults" | "presets" | "fields"> & {
  defaults: Record<string, unknown>;
  presets: Record<string, Record<string, unknown>>;
  fields: RawBalancerConfigField[];
};

const SUPPORTED_BALANCER_ALGORITHM_SET = new Set<string>(SUPPORTED_BALANCER_ALGORITHMS);
const SUPPORTED_BALANCER_CONFIG_KEY_SET = new Set<string>(SUPPORTED_BALANCER_CONFIG_KEYS);

function normalizeAlgorithm(
  value: unknown
): BalancerConfig["algorithm"] | undefined {
  if (typeof value !== "string") {
    return undefined;
  }

  return SUPPORTED_BALANCER_ALGORITHM_SET.has(value)
    ? (value as BalancerConfig["algorithm"])
    : undefined;
}

function sanitizeConfigForFrontend(
  config: BalancerConfig | Record<string, unknown> | null | undefined
): BalancerConfig {
  if (!config || typeof config !== "object") {
    return {};
  }

  const entries = Object.entries(config).flatMap(([key, value]) => {
    if (!SUPPORTED_BALANCER_CONFIG_KEY_SET.has(key) || value === undefined || value === null) {
      return [];
    }

    if (key === "algorithm") {
      const algorithm = normalizeAlgorithm(value);
      return algorithm ? [[key, algorithm]] : [];
    }

    return [[key, value]];
  });

  return Object.fromEntries(entries) as BalancerConfig;
}

function normalizeConfigField(
  field: RawBalancerConfigField,
  defaults: BalancerConfig
): BalancerConfigField | null {
  if (
    !SUPPORTED_BALANCER_CONFIG_KEY_SET.has(field.key) ||
    !SUPPORTED_CONFIG_FIELD_TYPES.has(field.type as string)
  ) {
    return null;
  }

  const options =
    field.key === "algorithm"
      ? (field.options ?? []).filter((option) => SUPPORTED_BALANCER_ALGORITHM_SET.has(option))
      : field.options;

  return {
    ...field,
    key: field.key as BalancerConfigField["key"],
    options,
    default: defaults[field.key as keyof BalancerConfig] ?? field.default
  };
}

function normalizeConfigResponse(payload: RawBalancerConfigResponse): BalancerConfigResponse {
  const defaults = sanitizeConfigForFrontend(payload.defaults);
  const presets = Object.fromEntries(
    Object.entries(payload.presets).flatMap(([presetName, presetConfig]) => {
      const algorithm = normalizeAlgorithm(presetConfig.algorithm);
      if (presetConfig.algorithm !== undefined && !algorithm) {
        return [];
      }

      return [[presetName, sanitizeConfigForFrontend(presetConfig)]];
    })
  );

  return {
    ...payload,
    defaults,
    presets,
    fields: payload.fields
      .map((field) => normalizeConfigField(field, defaults))
      .filter((field): field is BalancerConfigField => field !== null)
  };
}

export default class balancerService {
  static async getConfig(): Promise<BalancerConfigResponse> {
    try {
      const response = await apiFetch("balancer", "config", { timeout: 10_000 });
      const payload = (await response.json()) as RawBalancerConfigResponse;
      return normalizeConfigResponse(payload);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new Error("Failed to load balancer config: request timed out");
      }
      throw error;
    }
  }

  static async createBalanceJob(file: File, config?: BalancerConfig): Promise<BalanceJobCreateResponse> {
    const formData = new FormData();
    formData.append("player_data_file", file);

    if (config && Object.keys(config).length > 0) {
      formData.append("config_overrides", JSON.stringify(config));
    }

    try {
      const response = await apiFetch("balancer", "jobs", { method: "POST", body: formData, timeout: 20_000 });
      return response.json();
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new Error("Failed to create balancer job: request timed out");
      }
      throw error;
    }
  }

  static async getBalanceJobStatus(jobId: string): Promise<BalanceJobStatusResponse> {
    const response = await apiFetch("balancer", `jobs/${jobId}`, { timeout: 10_000 });
    return response.json();
  }

  static async getBalanceJobResult(jobId: string): Promise<BalanceJobResult> {
    const response = await apiFetch("balancer", `jobs/${jobId}/result`, { timeout: 20_000 });
    return response.json();
  }

  static async streamBalanceJob(
    jobId: string,
    handlers: {
      onEvent: (event: BalanceJobEvent) => void;
      onError?: (message: string) => void;
      onOpen?: () => void;
    }
  ): Promise<() => void> {
    const token = await getTokenFromCookies("aqt_access_token");
    const url = new URL(`${BALANCER_STREAM_PREFIX}/jobs/${jobId}/stream`, window.location.origin);

    if (token) {
      url.searchParams.set("token", token);
    }

    const source = new EventSource(url.toString(), {
      withCredentials: true
    });
    let isClosed = false;

    const close = () => {
      if (isClosed) {
        return;
      }

      isClosed = true;
      source.close();
    };

    source.onopen = () => {
      handlers.onOpen?.();
    };

    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as BalanceJobEvent;
        handlers.onEvent(payload);

        if (payload.status === "succeeded" || payload.status === "failed") {
          close();
        }
      } catch {
        handlers.onError?.("Failed to parse balancer stream event");
      }
    };

    source.onerror = () => {
      if (isClosed) {
        return;
      }

      handlers.onError?.("Lost connection to balancer stream");
    };

    return close;
  }
}
