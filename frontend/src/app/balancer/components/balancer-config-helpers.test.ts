import {
  CUSTOM_PRESET,
  areBalancerConfigsEqual,
  findMatchingPreset,
  getRunConfig,
  resolveInitialBalancerConfig,
  sanitizeBalancerConfig,
} from "./balancer-config-helpers";
import type { BalancerConfigResponse } from "@/types/balancer.types";

type TestFunction = () => void | Promise<void>;
type Expectation<T> = {
  toBe: (expected: T) => void;
  toEqual: (expected: unknown) => void;
};

declare const describe: (name: string, fn: TestFunction) => void;
declare const it: (name: string, fn: TestFunction) => void;
declare const expect: <T>(actual: T) => Expectation<T>;

const configData: BalancerConfigResponse = {
  defaults: {
    algorithm: "moo",
    population_size: 200,
  },
  limits: {},
  presets: {
    DEFAULT: {
      algorithm: "moo",
      population_size: 200,
    },
    QUICK: {
      algorithm: "moo",
      population_size: 50,
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
      findMatchingPreset(
        {
          population_size: 50,
          algorithm: "moo",
        },
        configData.presets
      )
    ).toBe("QUICK");
  });

  it("uses draft config as the run config for supported custom settings", () => {
    expect(getRunConfig({ max_result_variants: 6, algorithm: "cpsat" }, configData, CUSTOM_PRESET)).toEqual({
      algorithm: "cpsat",
      max_result_variants: 6,
    });
  });

  it("treats null and undefined values as unset when comparing configs", () => {
    expect(areBalancerConfigsEqual({ use_captains: undefined }, {})).toBe(true);
  });

  it("drops unsupported algorithms and unsupported config keys", () => {
    expect(
      sanitizeBalancerConfig(
        {
          algorithm: "legacy_solver",
          unsupported_weight: 2,
          max_result_variants: 5,
        } as unknown as Parameters<typeof sanitizeBalancerConfig>[0]
      )
    ).toEqual({
      max_result_variants: 5,
    });
  });

  it("treats mutation_rate_min as a numeric config key", () => {
    expect(sanitizeBalancerConfig({ mutation_rate_min: "0.25" as unknown as number })).toEqual({
      mutation_rate_min: 0.25,
    });
  });

  it("keeps rank_comfort_tilt in sanitized config", () => {
    const result = sanitizeBalancerConfig({ rank_comfort_tilt: 0.8 } as unknown as Parameters<typeof sanitizeBalancerConfig>[0]);
    expect(result.rank_comfort_tilt).toBe(0.8);
  });
});
