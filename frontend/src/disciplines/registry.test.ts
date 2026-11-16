import { describe, expect, it } from "vitest";

import { createDisciplineLoader } from "./registry/create";
import { loadAdminUI } from "./registry/admin";
import { loadAnalyticsUI } from "./registry/analytics";
import { loadPregameUI } from "./registry/pregame";
import { loadProfileUI } from "./registry/profile";
import { loadRankUI } from "./registry/rank";

const FAMILIES = {
  rank: loadRankUI,
  pregame: loadPregameUI,
  admin: loadAdminUI,
  profile: loadProfileUI,
  analytics: loadAnalyticsUI
};

describe("slot-family loaders", () => {
  it("resolve an unknown code to null, never to another game's module", async () => {
    for (const load of Object.values(FAMILIES)) {
      await expect(load("chess")).resolves.toBeNull();
      await expect(load("")).resolves.toBeNull();
      // Object prototype keys are not installed modules.
      await expect(load("constructor")).resolves.toBeNull();
      await expect(load("__proto__")).resolves.toBeNull();
    }
  });

  it("load Overwatch's slots of exactly their own family, memoised", async () => {
    const slotsOf = async (load: (code: string) => Promise<{ slots: object } | null>) =>
      Object.keys((await load("overwatch"))?.slots ?? {}).sort();

    expect(loadRankUI("overwatch")).toBe(loadRankUI("overwatch"));
    expect(await slotsOf(loadRankUI)).toEqual(["rankHistory"]);
    expect(await slotsOf(loadPregameUI)).toEqual(["pregameCharacterBans"]);
    expect(await slotsOf(loadAdminUI)).toEqual(["nativeRankEditor"]);
    expect(await slotsOf(loadProfileUI)).toEqual([
      "careerOverview",
      "careerTab",
      "characterCompare",
      "characterPopover",
      "characterStats",
      "lobbyRankTiles",
      "roleSignatures",
      "topCharacters",
      "tournamentSummary"
    ]);
    expect(await slotsOf(loadAnalyticsUI)).toEqual(["analytics"]);
    for (const load of Object.values(FAMILIES)) expect((await load("overwatch"))?.code).toBe("overwatch");
  });

  it("give LoL its own pregame renderer and no Overwatch renderer in any other family", async () => {
    const lol = await loadPregameUI("lol");
    expect(lol?.code).toBe("lol");
    expect(Object.keys(lol?.slots ?? {})).toEqual(["pregameCharacterBans"]);
    expect(lol?.slots.pregameCharacterBans).not.toBe((await loadPregameUI("overwatch"))?.slots.pregameCharacterBans);
    for (const load of [loadAdminUI, loadProfileUI, loadAnalyticsUI]) {
      await expect(load("lol")).resolves.toBeNull();
    }
    expect(Object.keys((await loadRankUI("lol"))?.slots ?? {})).toEqual(["rankHistory"]);
    expect((await loadRankUI("lol"))?.slots.rankHistory).not.toBe((await loadRankUI("overwatch"))?.slots.rankHistory);
  });

  it("keep a slot's component identity stable across loads", async () => {
    const first = await loadPregameUI("overwatch");
    const second = await loadPregameUI("overwatch");

    expect(second?.slots.pregameCharacterBans).toBe(first?.slots.pregameCharacterBans);
  });

  it("load a module once per code, however often it is asked for", async () => {
    let imports = 0;
    const load = createDisciplineLoader({
      chess: async () => {
        imports += 1;
        return { default: { code: "chess", slots: {} } };
      }
    });

    await Promise.all([load("chess"), load("chess")]);
    await load("chess");

    expect(imports).toBe(1);
  });

  it("retry a module whose chunk failed to load instead of keeping the failure", async () => {
    let imports = 0;
    const load = createDisciplineLoader({
      chess: async () => {
        imports += 1;
        if (imports === 1) throw new Error("ChunkLoadError");
        return { default: { code: "chess", slots: {} } };
      }
    });

    // A failed module is a rejection, not "no module" (`null`).
    await expect(load("chess")).rejects.toThrow("ChunkLoadError");
    await expect(load("chess")).resolves.toEqual({ code: "chess", slots: {} });
    await load("chess");

    expect(imports).toBe(2);
  });

  it("answer synchronously only for a settled load: never a pending or failed one, null for a game without a module", async () => {
    let imports = 0;
    const load = createDisciplineLoader({
      chess: async () => {
        imports += 1;
        if (imports === 1) throw new Error("ChunkLoadError");
        return { default: { code: "chess", slots: {} } };
      }
    });

    expect(load.peek("go")).toBeNull();
    const failed = load("chess");
    expect(load.peek("chess")).toBeUndefined();
    await expect(failed).rejects.toThrow("ChunkLoadError");
    expect(load.peek("chess")).toBeUndefined();

    const ui = await load("chess");
    expect(load.peek("chess")).toBe(ui);
  });
});
