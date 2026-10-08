import { beforeEach, describe, expect, it, vi } from "vitest";

// `vi.hoisted` because `vi.mock` is lifted above the imports: the spy has to
// exist before the mocked module factory runs.
const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));

vi.mock("@/lib/api/fetch", () => ({ apiFetch }));

import balancerService from "./balancer.service";

/** Shaped like `GET /api/v1/balancer/config`: `fields` is the server's catalog of
 * knobs, `defaults`/`presets` are values keyed by knob name. */
function configPayload() {
  return {
    defaults: {
      population_size: 100,
      team_max_pain_weight: 0.6,
      time_limit_ms: 600000,
      rank_comfort_tilt: 0.45,
      role_settings: { tank: { impact: 1.4 } },
      max_result_variants: null,
    },
    limits: { population_size: { min: 10, max: 1000 } },
    presets: { DEFAULT: { population_size: 100, max_result_variants: null } },
    fields: [
      {
        key: "population_size",
        label: "Population size",
        description: "d",
        type: "integer",
        group: "Algorithm",
        default: 100,
        limits: { min: 10, max: 1000 },
      },
      {
        key: "team_max_pain_weight",
        label: "Per-team worst discomfort",
        description: "d",
        type: "float",
        group: "Quality weights",
        default: 0.6,
        limits: { min: 0, max: 10000 },
      },
      {
        key: "time_limit_ms",
        label: "Time limit (ms)",
        description: "d",
        type: "integer",
        group: "Strategy",
        default: 600000,
        limits: { min: 100, max: 600000 },
      },
      {
        key: "some_future_knob",
        label: "Future knob",
        description: "d",
        type: "float",
        group: "Strategy",
        default: 1,
        limits: null,
      },
      {
        key: "legacy_widget",
        label: "Legacy widget",
        description: "d",
        type: "role_mask",
        group: "Algorithm",
        default: {},
        limits: null,
      },
      {
        key: "role_settings",
        label: "Role weights",
        description: "d",
        type: "roles",
        group: "Quality weights",
        default: { tank: { impact: 1.4 }, damage: { impact: 1 } },
        limits: null,
        columns: [{ key: "impact", label: "Impact", description: "d", limits: { min: 0, max: 10 } }],
      },
    ],
  };
}

beforeEach(() => {
  apiFetch.mockReset();
  apiFetch.mockResolvedValue({ json: async () => configPayload() });
});

describe("balancerService.getConfig", () => {
  it("renders every knob the server ships, including ones no client list knew about", async () => {
    const config = await balancerService.getConfig();

    // `team_max_pain_weight` and `time_limit_ms` were editable server-side while
    // a hand-written client allowlist silently dropped them from both the drawer
    // and the outgoing request; `some_future_knob` stands for the next one.
    expect(config.fields.map((field) => field.key)).toEqual([
      "population_size",
      "team_max_pain_weight",
      "time_limit_ms",
      "some_future_knob",
      "role_settings",
    ]);
  });

  it("drops a row typed as a widget the drawer cannot render", async () => {
    const config = await balancerService.getConfig();

    // Falling through to the number input would stringify the value and write
    // garbage back into the config.
    expect(config.fields.some((field) => field.key === "legacy_widget")).toBe(false);
  });

  it("treats a null knob as absent so presets keep matching", async () => {
    const config = await balancerService.getConfig();

    expect("max_result_variants" in config.defaults).toBe(false);
    expect("max_result_variants" in config.presets.DEFAULT).toBe(false);
  });

  it("prefers the live default over the one baked into the field row", async () => {
    apiFetch.mockResolvedValue({
      json: async () => ({ ...configPayload(), defaults: { population_size: 250 } }),
    });

    const config = await balancerService.getConfig();

    expect(config.fields.find((field) => field.key === "population_size")?.default).toBe(250);
  });
});
