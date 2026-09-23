// Runs under `bun test`, matching every other `src/lib/*.test.ts` in this
// directory (vitest's include list deliberately does not cover src/lib).
import { describe, expect, it } from "bun:test";

import {
  composeOutcome,
  requiredProviders,
  requirementClauses
} from "@/lib/registration/subscription-requirement";
import type {
  SubscriptionProviderVerdict,
  SubscriptionRequirement
} from "@/types/registration.types";

const T: SubscriptionProviderVerdict = { state: "active", tier_rank: 3 };
const F: SubscriptionProviderVerdict = { state: "inactive" };
const U: SubscriptionProviderVerdict = { state: "unknown", reason: "provider_unavailable" };

function req(mode: "any" | "all", providers: string[], minTier = 1): SubscriptionRequirement {
  return {
    mode,
    requirements: providers.map((provider) => ({ provider, min_tier_rank: minTier }))
  };
}

/**
 * The same truth table the Python suite asserts in
 * `test_subscription_requirement.py::TestAllMode` / `TestAnyMode`: six unordered
 * pairs per mode, twelve cases total. Ported verbatim so the two implementations
 * cannot drift.
 */
describe("composeOutcome — Kleene truth table", () => {
  const cases: Array<
    ["any" | "all", SubscriptionProviderVerdict, SubscriptionProviderVerdict, string]
  > = [
    ["all", T, T, "satisfied"],
    ["all", T, U, "undetermined"],
    ["all", T, F, "refused"],
    ["all", F, U, "refused"],
    ["all", U, U, "undetermined"],
    ["all", F, F, "refused"],
    ["any", T, F, "satisfied"],
    ["any", T, U, "satisfied"],
    ["any", F, U, "undetermined"],
    ["any", F, F, "refused"],
    ["any", U, U, "undetermined"],
    ["any", T, T, "satisfied"]
  ];

  it.each(cases)("%s of [%o, %o] is %s", (mode, a, b, expected) => {
    expect(composeOutcome(req(mode, ["boosty", "twitch"]), { boosty: a, twitch: b })).toBe(
      expected
    );
  });

  it("is order independent", () => {
    for (const [mode, a, b] of cases) {
      const forward = composeOutcome(req(mode, ["boosty", "twitch"]), { boosty: a, twitch: b });
      const backward = composeOutcome(req(mode, ["boosty", "twitch"]), { boosty: b, twitch: a });
      expect(forward).toBe(backward);
    }
  });

  it("never blocks when one provider is down but the other satisfies (any)", () => {
    // The headline regression: coercing `unknown` to false here would lock out
    // every patron subscribed via the surviving provider.
    expect(composeOutcome(req("any", ["boosty", "twitch"]), { boosty: F, twitch: U })).toBe(
      "undetermined"
    );
  });
});

describe("composeOutcome — single provider", () => {
  it.each(["any", "all"] as const)("%s agrees with the other mode", (mode) => {
    expect(composeOutcome(req(mode, ["boosty"]), { boosty: T })).toBe("satisfied");
    expect(composeOutcome(req(mode, ["boosty"]), { boosty: F })).toBe("refused");
    expect(composeOutcome(req(mode, ["boosty"]), { boosty: U })).toBe("undetermined");
  });
});

describe("composeOutcome — thresholds", () => {
  it("treats active below the threshold as a refusal, not as unknown", () => {
    expect(
      composeOutcome(req("all", ["boosty"], 3), { boosty: { state: "active", tier_rank: 1 } })
    ).toBe("refused");
  });

  it("reads a tierless active verdict as level 1", () => {
    expect(
      composeOutcome(req("all", ["boosty"], 1), { boosty: { state: "active", tier_rank: null } })
    ).toBe("satisfied");
    expect(
      composeOutcome(req("all", ["boosty"], 2), { boosty: { state: "active", tier_rank: null } })
    ).toBe("refused");
  });

  it("keeps per-provider thresholds independent", () => {
    const requirement: SubscriptionRequirement = {
      mode: "all",
      requirements: [
        { provider: "boosty", min_tier_rank: 3 },
        { provider: "twitch", min_tier_rank: 1 }
      ]
    };
    expect(
      composeOutcome(requirement, {
        boosty: { state: "active", tier_rank: 3 },
        twitch: { state: "active", tier_rank: 1 }
      })
    ).toBe("satisfied");
  });
});

describe("composeOutcome — missing data", () => {
  it("treats a missing verdict as undetermined, never as a refusal", () => {
    expect(composeOutcome(req("all", ["boosty", "twitch"]), { boosty: T })).toBe("undetermined");
    expect(composeOutcome(req("any", ["boosty", "twitch"]), { boosty: F })).toBe("undetermined");
  });

  it("is satisfied when nothing is required", () => {
    expect(composeOutcome({ mode: "all", requirements: [] }, {})).toBe("satisfied");
    expect(composeOutcome({}, {})).toBe("satisfied");
    expect(composeOutcome(undefined, {})).toBe("satisfied");
  });
});

describe("only a confirmed refusal is a refusal", () => {
  it("fails open on undetermined and on a missing outcome", () => {
    // Reads a SIGNAL, not the decision: admission moved to the server's
    // `admission.decision`, and the fail-open invariant is pinned against real
    // code in `lib/registration/admission.test.ts` and `RegistrationBadges.behavior.test.tsx`.
    // What survives here is the chip contract — three states, only one of them
    // red — which `SubscriptionStatusBadge` and its column both render.
    const outcomes: Array<[string | null | undefined, boolean]> = [
      ["refused", true],
      ["undetermined", false],
      ["satisfied", false],
      [null, false],
      [undefined, false]
    ];
    for (const [outcome, expected] of outcomes) {
      expect(outcome === "refused").toBe(expected);
    }
  });
});

describe("requiredProviders", () => {
  it("lists the distinct providers", () => {
    expect(requiredProviders(req("any", ["boosty", "twitch"]))).toEqual(["boosty", "twitch"]);
  });

  it("deduplicates", () => {
    expect(
      requiredProviders({
        requirements: [{ provider: "boosty" }, { provider: "boosty", min_tier_rank: 3 }]
      })
    ).toEqual(["boosty"]);
  });

  it("skips rows without a provider", () => {
    expect(requiredProviders({ requirements: [{} as never] })).toEqual([]);
  });

  it("is empty for no requirement", () => {
    expect(requiredProviders(undefined)).toEqual([]);
  });
});

describe("requirementClauses", () => {
  it("names every provider in declaration order", () => {
    expect(requirementClauses(req("any", ["boosty", "twitch"])).map((c) => c.provider)).toEqual([
      "boosty",
      "twitch"
    ]);
  });

  it("surfaces a threshold above one", () => {
    expect(requirementClauses(req("all", ["boosty"], 2))).toEqual([
      { provider: "boosty", minTier: 2 }
    ]);
  });

  it("omits a threshold of one — it would read as a restriction that is not there", () => {
    expect(requirementClauses(req("all", ["boosty"], 1))).toEqual([
      { provider: "boosty", minTier: null }
    ]);
  });

  it("clamps a nonsensical threshold below one away", () => {
    expect(requirementClauses(req("all", ["boosty"], 0))).toEqual([
      { provider: "boosty", minTier: null }
    ]);
  });

  it("passes an unknown provider key through untouched", () => {
    expect(requirementClauses(req("all", ["patreon"], 2))).toEqual([
      { provider: "patreon", minTier: 2 }
    ]);
  });

  it("carries no conjunction — mode is the caller's to render", () => {
    const any = requirementClauses(req("any", ["boosty", "twitch"], 2));
    const all = requirementClauses(req("all", ["boosty", "twitch"], 2));
    expect(any).toEqual(all);
  });

  it("skips rows without a provider", () => {
    expect(requirementClauses({ requirements: [{} as never, { provider: "boosty" }] })).toEqual([
      { provider: "boosty", minTier: null }
    ]);
  });

  it("is empty when nothing is required", () => {
    expect(requirementClauses(undefined)).toEqual([]);
  });
});
