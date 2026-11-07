import { describe, expect, it } from "vitest";

import {
  buildBalancerPageCollections,
  poolMismatch,
  replaceVariantPayload,
  upsertSavedVariant,
} from "./balancer-page-selectors";
import type { BalancerPlayerRecord, InternalBalancePlayer } from "@/types/balancer-admin.types";
import type { BalanceVariant } from "@/components/balancer/workspace-helpers";
import { OW_REFERENCE_GRID } from "@/disciplines/overwatch/ladder/ow-reference-grid";
import type { AdminRegistration, InternalBalancePayload } from "@/types/balancer-admin.types";

function createPayload(teamName: string): InternalBalancePayload {
  return {
    teams: [
      {
        id: 1,
        name: teamName,
        average_mmr: 2500,
        roster: { tank: [], damage: [], support: [] },
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
      primary_handle: `Player${id}#1000`,
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
      OW_REFERENCE_GRID,
      (code) => code,
      "battlenet",
    );

    expect(collections.allPlayerValidationStates.map((state) => state.player.id)).toEqual([1]);
    expect(collections.poolPlayers.map((player) => player.id)).toEqual([1]);
    expect([...collections.registrationsById.keys()]).toEqual([1]);
  });
});

describe("poolMismatch", () => {
  const record = (id: number) => ({ id }) as BalancerPlayerRecord;
  const placed = (id: number, name: string) => ({ uuid: String(id), name }) as InternalBalancePlayer;
  const payload = (teamIds: [number, string][], benched: [number, string][] = []): InternalBalancePayload => ({
    teams: [
      { id: 1, name: "A", average_mmr: 0, roster: { tank: teamIds.map(([id, name]) => placed(id, name)), damage: [], support: [] } }
    ],
    benched_players: benched.map(([id, name]) => placed(id, name))
  });

  it("agrees when every ready player is seated or spare and nobody comes from outside the pool", () => {
    expect(poolMismatch(payload([[1, "One"]], [[2, "Two"]]), [record(1), record(2)], [record(1), record(2)])).toBeNull();
  });

  it("names a ready player the balance lost and a player it holds from outside the pool", () => {
    const mismatch = poolMismatch(payload([[1, "One"], [9, "Excluded"]]), [record(1), record(2)], [record(1), record(2)]);

    expect(mismatch?.missing.map((player) => player.id)).toEqual([2]);
    expect(mismatch?.outside).toEqual(["Excluded"]);
  });

  it("does not count a pool player with blocking issues, who may be skipped on purpose", () => {
    expect(poolMismatch(payload([[1, "One"]]), [record(1)], [record(1), record(3)])).toBeNull();
  });
});
