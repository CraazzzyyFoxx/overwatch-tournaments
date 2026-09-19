import { describe, expect, it } from "vitest";

import { replaceVariantPayload, upsertSavedVariant } from "./balancer-page-selectors";
import type { BalanceVariant } from "@/components/balancer/workspace-helpers";
import type { InternalBalancePayload } from "@/types/balancer-admin.types";

function createPayload(teamName: string): InternalBalancePayload {
  return {
    teams: [
      {
        id: 1,
        name: teamName,
        average_mmr: 2500,
        roster: { Tank: [], Damage: [], Support: [] },
      },
    ],
  };
}

function createSavedVariant(): BalanceVariant {
  return {
    id: "saved-1",
    label: "Saved balance #1",
    payload: createPayload("Team A"),
    source: "saved",
  };
}

describe("replaceVariantPayload", () => {
  it("marks the edited variant dirty so Save/Export re-enable", () => {
    const [variant] = replaceVariantPayload(
      [createSavedVariant()],
      "saved-1",
      createPayload("Team B"),
    );

    expect(variant.payload.teams[0].name).toBe("Team B");
    expect(variant.dirty).toBe(true);
  });

  it("leaves other variants untouched", () => {
    const generated: BalanceVariant = {
      id: "generated-1",
      label: "Balance #1",
      payload: createPayload("Team A"),
      source: "generated",
    };

    const [, other] = replaceVariantPayload(
      [createSavedVariant(), generated],
      "saved-1",
      createPayload("Team B"),
    );

    expect(other.dirty).toBeUndefined();
  });
});

describe("upsertSavedVariant", () => {
  it("replaces a dirty saved variant with the clean persisted one", () => {
    const edited = replaceVariantPayload(
      [createSavedVariant()],
      "saved-1",
      createPayload("Team B"),
    );

    const [saved] = upsertSavedVariant(edited, createSavedVariant());

    expect(saved.dirty).toBeUndefined();
    expect(saved.payload.teams[0].name).toBe("Team A");
  });
});
