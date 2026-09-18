import {
  BalanceJobCreateResponse,
  BalanceJobResult,
  BalanceJobStatusResponse,
  BalancerConfig,
  BalancerConfigResponse,
  BalancerConfigField
} from "@/types/balancer.types";
import { apiFetch } from "@/lib/api-fetch";

/** Widgets the drawer can render. A row typed anything else is dropped rather
 * than handed to `ConfigFieldControl`, which would fall through to a number
 * input and mangle the value. Which KEYS exist is not checked here: that is the
 * backend's answer and this response is it. */
const SUPPORTED_CONFIG_FIELD_TYPES: Record<string, true> = {
  boolean: true,
  float: true,
  integer: true,
  slider: true
};

type RawBalancerConfigField = Omit<BalancerConfigField, "type"> & {
  type: string;
};

type RawBalancerConfigResponse = Omit<BalancerConfigResponse, "defaults" | "presets" | "fields"> & {
  defaults: Record<string, unknown>;
  presets: Record<string, Record<string, unknown>>;
  fields: RawBalancerConfigField[];
};

/** A knob the server left null is an absent knob, not a knob set to null:
 * `null` would survive `sanitizeBalancerConfig` comparisons as a real value and
 * make every preset look custom. */
function dropEmptyConfigValues(config: Record<string, unknown>): BalancerConfig {
  return Object.fromEntries(
    Object.entries(config).filter(([, value]) => value !== undefined && value !== null)
  ) as BalancerConfig;
}

function normalizeConfigResponse(payload: RawBalancerConfigResponse): BalancerConfigResponse {
  const defaults = dropEmptyConfigValues(payload.defaults);

  return {
    ...payload,
    defaults,
    presets: Object.fromEntries(
      Object.entries(payload.presets).map(([name, preset]) => [name, dropEmptyConfigValues(preset)])
    ),
    fields: payload.fields
      .filter((field) => SUPPORTED_CONFIG_FIELD_TYPES[field.type])
      .map((field) => ({
        ...(field as BalancerConfigField),
        default: defaults[field.key] ?? field.default
      }))
  };
}

export default class balancerService {
  static async getConfig(): Promise<BalancerConfigResponse> {
    try {
      const response = await apiFetch("/api/balancer/config", { timeout: 10_000 });
      const payload = (await response.json()) as RawBalancerConfigResponse;
      return normalizeConfigResponse(payload);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new Error("Failed to load balancer config: request timed out");
      }
      throw error;
    }
  }

  /**
   * Runs the tournament's own pool through the solver. The player payload is
   * assembled server-side from the roster engine — the browser sends only the
   * config it wants, never a rebuilt copy of everyone's roles and ranks.
   *
   * The route is tournament-scoped, so job status fans out over that
   * tournament's realtime topic to everyone with the balancer page open.
   */
  static async createTournamentBalanceJob(params: {
    tournament_id: number;
    config_overrides?: BalancerConfig | null;
  }): Promise<BalanceJobCreateResponse> {
    try {
      const response = await apiFetch(
        `/api/balancer/tournaments/${params.tournament_id}/balance`,
        {
          method: "POST",
          body: { config_overrides: params.config_overrides ?? null },
          timeout: 20_000
        }
      );
      return response.json();
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new Error("Failed to create balancer job: request timed out");
      }
      throw error;
    }
  }

  static async getBalanceJobStatus(jobId: string): Promise<BalanceJobStatusResponse> {
    const response = await apiFetch(`/api/balancer/jobs/${jobId}`, { timeout: 10_000 });
    return response.json();
  }

  static async getBalanceJobResult(jobId: string): Promise<BalanceJobResult> {
    const response = await apiFetch(`/api/balancer/jobs/${jobId}/result`, { timeout: 20_000 });
    return response.json();
  }
}
