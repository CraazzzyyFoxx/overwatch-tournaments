import { describe, expect, it } from "bun:test";

import {
  participantColumnsStorageKey,
  participantDefaultColumnIds,
  participantResultsScrollTarget,
  participantResultsTransitionSignature,
  normalizeParticipantSearch,
  readParticipantUrlState,
  readStoredParticipantColumnIds,
  shouldScrollParticipantResults,
  updateParticipantUrlState,
  writeStoredParticipantColumnIds,
} from "./participants-url-state";

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
    removeItem: (key: string) => {
      data.delete(key);
    },
  };
}

const columns = [
  { id: "battle_tag", defaultVisible: true },
  { id: "roles", defaultVisible: true },
  { id: "notes", defaultVisible: false },
  { id: "_status", defaultVisible: true },
];

describe("participant URL state", () => {
  it("removes control characters, trims search, and caps it at 120 characters", () => {
    expect(normalizeParticipantSearch(` \u0000Ana\u0085${"x".repeat(140)} `)).toBe(
      `Ana${"x".repeat(117)}`,
    );
  });

  it("falls back to defaults when invalid columns are mixed with legacy core ids", () => {
    const result = readParticipantUrlState(
      new URLSearchParams(
        "participantStatus=unknown&participantColumns=battle_tag,unknown&tab=rules",
      ),
      ["approved", "pending"],
      columns,
    );

    expect(result.state).toEqual({
      search: "",
      status: "all",
      visibleColumnIds: ["battle_tag", "_status", "roles"],
    });
    expect(result.needsNormalization).toBe(true);
    expect(result.params.toString()).toBe("tab=rules");
    expect(
      readParticipantUrlState(result.params, ["approved", "pending"], columns)
        .needsNormalization,
    ).toBe(false);
  });

  it("removes explicit defaults and restores custom status/column state deterministically", () => {
    const defaults = readParticipantUrlState(
      new URLSearchParams(
        "participantSearch=%20%00%20&participantStatus=all&participantColumns=battle_tag,roles,_status",
      ),
      ["approved", "custom_review"],
      columns,
    );
    const restored = readParticipantUrlState(
      new URLSearchParams(
        "participantStatus=custom_review&participantColumns=notes,battle_tag",
      ),
      ["approved", "custom_review"],
      columns,
    );

    expect(defaults.params.toString()).toBe("");
    expect(restored.state).toEqual({
      search: "",
      status: "custom_review",
      visibleColumnIds: ["battle_tag", "_status", "notes"],
    });
    expect(restored.params.get("participantColumns")).toBe("notes");
  });

  it("distinguishes none, invalid, mixed, and legacy core-only column selections", () => {
    const none = readParticipantUrlState(
      new URLSearchParams("participantColumns=none"),
      ["approved"],
      columns,
    );
    const unsupported = readParticipantUrlState(
      new URLSearchParams("participantColumns=unknown,bogus"),
      ["approved"],
      columns,
    );
    const custom = readParticipantUrlState(
      new URLSearchParams("participantColumns=notes,unknown,battle_tag"),
      ["approved"],
      columns,
    );
    const legacyCoreOnly = readParticipantUrlState(
      new URLSearchParams("participantColumns=battle_tag,_status"),
      ["approved"],
      columns,
    );

    expect(none.state.visibleColumnIds).toEqual(["battle_tag", "_status"]);
    expect(none.params.get("participantColumns")).toBe("none");
    expect(unsupported.state.visibleColumnIds).toEqual([
      "battle_tag",
      "_status",
      "roles",
    ]);
    expect(unsupported.params.get("participantColumns")).toBeNull();
    expect(custom.state.visibleColumnIds).toEqual(["battle_tag", "_status", "notes"]);
    expect(custom.params.get("participantColumns")).toBe("notes");
    // Core ids were valid selectable columns in legacy URLs, so core-only means no optionals.
    expect(legacyCoreOnly.state.visibleColumnIds).toEqual(["battle_tag", "_status"]);
    expect(legacyCoreOnly.params.get("participantColumns")).toBe("none");
  });

  it("uses replace for search and push for discrete filters while preserving other params", () => {
    const current = new URLSearchParams("tab=rules");
    const searchUpdate = updateParticipantUrlState(current, {
      type: "search",
      value: "  Ana  ",
    });
    const statusUpdate = updateParticipantUrlState(searchUpdate.params, {
      type: "status",
      value: "approved",
    });

    expect(searchUpdate.history).toBe("replace");
    expect(statusUpdate.history).toBe("push");
    expect(statusUpdate.params.toString()).toContain("tab=rules");
    expect(statusUpdate.params.get("participantSearch")).toBe("Ana");
    expect(statusUpdate.params.get("participantStatus")).toBe("approved");
  });

  it("reset removes only participant-owned parameters and never adds pagination", () => {
    const result = updateParticipantUrlState(
      new URLSearchParams(
        "participantSearch=Ana&participantStatus=pending&participantColumns=none&tab=rules",
      ),
      { type: "reset" },
    );

    expect(result.history).toBe("push");
    expect(result.params.toString()).toBe("tab=rules");
    expect(result.params.toString()).not.toMatch(/page|pagination/i);
  });

  it("pushes column changes and omits the default column set", () => {
    const changed = updateParticipantUrlState(new URLSearchParams("tab=rules"), {
      type: "columns",
      value: ["battle_tag", "_status", "notes"],
      defaultValue: ["battle_tag", "_status", "roles"],
    });
    const reset = updateParticipantUrlState(changed.params, {
      type: "columns",
      value: ["battle_tag", "_status", "roles"],
      defaultValue: ["battle_tag", "_status", "roles"],
    });

    expect(changed.history).toBe("push");
    expect(changed.params.get("participantColumns")).toBe("notes");
    expect(reset.params.get("participantColumns")).toBeNull();
    expect(reset.params.get("tab")).toBe("rules");
  });

  it("scrolls back to results only when the viewport is already below the heading", () => {
    expect(
      shouldScrollParticipantResults({
        scrollY: 900,
        headingDocumentTop: 620,
        stickyOffset: 76,
      }),
    ).toBe(true);
    expect(
      shouldScrollParticipantResults({
        scrollY: 200,
        headingDocumentTop: 620,
        stickyOffset: 76,
      }),
    ).toBe(false);
    expect(participantResultsScrollTarget(620, 76)).toBe(532);
  });

  it("triggers result scrolling only for normalized URL-owned filter transitions", () => {
    const baseUrlState = {
      search: "ana",
      status: "approved",
      visibleColumnIds: ["battle_tag", "_status", "roles"],
    };
    const beforeResult = {
      ...baseUrlState,
      registrationIds: [1, 2, 3],
    };
    const realtimeResult = {
      ...baseUrlState,
      registrationIds: [4, 3, 2, 1],
    };
    const backForwardResult = {
      ...baseUrlState,
      status: "pending",
      registrationIds: [4, 3, 2, 1],
    };
    const before = participantResultsTransitionSignature(beforeResult);
    const realtimeReorder = participantResultsTransitionSignature(realtimeResult);
    const backForwardFilter = participantResultsTransitionSignature(backForwardResult);

    expect(realtimeReorder).toBe(before);
    expect(backForwardFilter).not.toBe(before);
  });
  it("computes the same default set the Reset button applies (mandatory first)", () => {
    const defaults = participantDefaultColumnIds(columns);

    expect(defaults).toEqual(["battle_tag", "_status", "roles"]);
    expect(
      readParticipantUrlState(new URLSearchParams(), ["approved"], columns).state
        .visibleColumnIds,
    ).toEqual(defaults);
  });

  it("seeds visible columns from the stored selection without touching the URL", () => {
    const stored = readParticipantUrlState(
      new URLSearchParams("tab=rules"),
      ["approved"],
      columns,
      ["notes"],
    );
    const storedNone = readParticipantUrlState(
      new URLSearchParams(),
      ["approved"],
      columns,
      [],
    );
    const storedInvalid = readParticipantUrlState(
      new URLSearchParams(),
      ["approved"],
      columns,
      ["ghost_column"],
    );

    expect(stored.state.visibleColumnIds).toEqual(["battle_tag", "_status", "notes"]);
    expect(stored.needsNormalization).toBe(false);
    expect(stored.params.toString()).toBe("tab=rules");
    expect(storedNone.state.visibleColumnIds).toEqual(["battle_tag", "_status"]);
    expect(storedInvalid.state.visibleColumnIds).toEqual([
      "battle_tag",
      "_status",
      "roles",
    ]);
  });

  it("lets an explicit URL selection win over the stored selection", () => {
    const result = readParticipantUrlState(
      new URLSearchParams("participantColumns=roles"),
      ["approved"],
      columns,
      ["notes"],
    );

    expect(result.state.visibleColumnIds).toEqual(["battle_tag", "_status", "roles"]);
  });

  it("round-trips the stored selection and removes it for defaults or garbage", () => {
    const storage = memoryStorage();
    const defaults = participantDefaultColumnIds(columns);

    expect(
      writeStoredParticipantColumnIds(storage, 7, ["battle_tag", "_status", "notes"], defaults),
    ).toEqual(["notes"]);
    expect(readStoredParticipantColumnIds(storage, 7)).toEqual(["notes"]);
    // Another tournament never sees a foreign selection.
    expect(readStoredParticipantColumnIds(storage, 8)).toBeNull();

    expect(writeStoredParticipantColumnIds(storage, 7, defaults, defaults)).toBeNull();
    expect(readStoredParticipantColumnIds(storage, 7)).toBeNull();
    expect(storage.data.has(participantColumnsStorageKey(7))).toBe(false);

    const garbage = memoryStorage({
      [participantColumnsStorageKey(9)]: "{not json",
      [participantColumnsStorageKey(10)]: JSON.stringify({ nope: true }),
    });
    expect(readStoredParticipantColumnIds(garbage, 9)).toBeNull();
    expect(readStoredParticipantColumnIds(garbage, 10)).toBeNull();
    expect(readStoredParticipantColumnIds(null, 9)).toBeNull();
  });
});
