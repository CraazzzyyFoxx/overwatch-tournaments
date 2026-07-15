import { describe, expect, it } from "bun:test";

import {
  participantResultsScrollTarget,
  normalizeParticipantSearch,
  readParticipantUrlState,
  shouldScrollParticipantResults,
  updateParticipantUrlState,
} from "./participants-url-state";

const columns = [
  { id: "battle_tag", defaultVisible: true },
  { id: "roles", defaultVisible: true },
  { id: "notes", defaultVisible: false },
];

describe("participant URL state", () => {
  it("removes control characters, trims search, and caps it at 120 characters", () => {
    expect(normalizeParticipantSearch(` \u0000Ana\u0085${"x".repeat(140)} `)).toBe(
      `Ana${"x".repeat(117)}`,
    );
  });

  it("omits defaults and normalizes unsupported status and columns", () => {
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
      visibleColumnIds: ["battle_tag"],
    });
    expect(result.needsNormalization).toBe(true);
    expect(result.params.toString()).toBe("participantColumns=battle_tag&tab=rules");
    expect(
      readParticipantUrlState(result.params, ["approved", "pending"], columns)
        .needsNormalization,
    ).toBe(false);
  });

  it("removes explicit defaults and restores custom status/column state deterministically", () => {
    const defaults = readParticipantUrlState(
      new URLSearchParams(
        "participantSearch=%20%00%20&participantStatus=all&participantColumns=battle_tag,roles",
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
      visibleColumnIds: ["battle_tag", "notes"],
    });
    expect(restored.params.get("participantColumns")).toBe("battle_tag,notes");
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
      value: ["battle_tag", "notes"],
      defaultValue: ["battle_tag", "roles"],
    });
    const reset = updateParticipantUrlState(changed.params, {
      type: "columns",
      value: ["battle_tag", "roles"],
      defaultValue: ["battle_tag", "roles"],
    });

    expect(changed.history).toBe("push");
    expect(changed.params.get("participantColumns")).toBe("battle_tag,notes");
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
});
