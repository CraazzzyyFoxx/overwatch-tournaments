import { describe, expect, it } from "vitest";

import {
  CUSTOM_PRESET,
  areBalancerConfigsEqual,
  findMatchingPreset,
  getRunConfig,
  resolveInitialBalancerConfig,
  sanitizeBalancerConfig,
} from "./balancer-config-helpers";
import type { BalancerConfigResponse } from "@/types/balancer.types";

const configData: BalancerConfigResponse = {
  defaults: {
    population_size: 200,
    max_result_variants: 10,
  },
  limits: {},
  presets: {
    DEFAULT: {
      population_size: 200,
      max_result_variants: 10,
    },
    QUICK: {
      population_size: 50,
      max_result_variants: 10,
    },
  },
  fields: [],
};

describe("balancer config helpers", () => {
  it("resolves tournament config before runtime defaults", () => {
    expect(resolveInitialBalancerConfig(configData, { population_size: 150 })).toEqual({
      population_size: 150,
    });
  });

  it("matches presets regardless of object key order", () => {
    expect(
      findMatchingPreset({ max_result_variants: 10, population_size: 50 }, configData.presets)
    ).toBe("QUICK");
  });

  it("uses draft config as the run config for supported custom settings", () => {
    expect(getRunConfig({ max_result_variants: 6 }, configData, CUSTOM_PRESET)).toEqual({
      max_result_variants: 6,
    });
  });

  it("treats null and undefined values as unset when comparing configs", () => {
    expect(areBalancerConfigsEqual({ use_captains: undefined }, {})).toBe(true);
    expect(areBalancerConfigsEqual({ population_size: null }, {})).toBe(true);
  });

  it("coerces a number input's raw string to a number", () => {
    expect(sanitizeBalancerConfig({ mutation_rate_min: "0.25" })).toEqual({
      mutation_rate_min: 0.25,
    });
  });

  it("drops a cleared number input instead of sending an empty string", () => {
    expect(sanitizeBalancerConfig({ population_size: "  ", generation_count: "abc" })).toEqual({});
  });

  it("keeps knobs the backend added without a client-side allowlist to update", () => {
    // The whole point of dropping the hand-written key list: a knob the backend
    // starts shipping reaches the request without a frontend release. Both of
    // these were editable server-side while the old allowlist silently ate them.
    expect(
      sanitizeBalancerConfig({ team_max_pain_weight: 0.6, time_limit_ms: 30000 })
    ).toEqual({ team_max_pain_weight: 0.6, time_limit_ms: 30000 });
  });

  it("keeps rank_comfort_tilt in sanitized config", () => {
    expect(sanitizeBalancerConfig({ rank_comfort_tilt: 0.8 }).rank_comfort_tilt).toBe(0.8);
  });
});
