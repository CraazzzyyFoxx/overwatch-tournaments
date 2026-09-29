import { describe, expect, it } from "vitest";

import {
  buildBalancerPageCollections,
  replaceVariantPayload,
  upsertSavedVariant,
} from "./balancer-page-selectors";
import type { BalanceVariant } from "@/components/balancer/workspace-helpers";
import { DEFAULT_DIVISION_GRID } from "@/lib/divisions/grid";
import type { AdminRegistration, InternalBalancePayload } from "@/types/balancer-admin.types";

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

describe("buildBalancerPageCollections", () => {
  function registration(id: number, status: string): AdminRegistration {
    return {
      id,
      tournament_id: 60,
      user_id: id,
      battle_tag: `Player${id}#1000`,
      battle_tag_normalized: `player${id}#1000`,
      display_name: null,
      answers: {},
      roles: [],
      is_flex: false,
      status,
      balancer_status: "ready",
      balancer_status_meta: { excludes_from_balancer: false, excludes_from_ready: false },
      deleted_at: null,
      submitted_at: null,
      reviewed_at: null,
      admin_notes: null,
    } as unknown as AdminRegistration;
  }

  it("lists only approved registrations, neither pooling nor excluding the rest", () => {
    const collections = buildBalancerPageCollections(
      [
        registration(1, "approved"),
        registration(2, "withdrawn"),
        registration(3, "rejected"),
        registration(4, "pending"),
      ],
      DEFAULT_DIVISION_GRID,
    );

    expect(collections.allPlayerValidationStates.map((state) => state.player.id)).toEqual([1]);
    expect(collections.poolPlayers.map((player) => player.id)).toEqual([1]);
    expect([...collections.registrationsById.keys()]).toEqual([1]);
  });
});
