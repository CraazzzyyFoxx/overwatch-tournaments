import { describe, expect, it } from "vitest";

import {
  parseFiltersFromParams,
  serializeFilters,
  writeFiltersToParams,
  type AdminColumnFilterSpec
} from "./filters";

const statusSpec: AdminColumnFilterSpec = {
  param: "status",
  options: [
    { value: "OPEN", label: "Open" },
    { value: "PENDING", label: "Pending" }
  ]
};

const entitiesSpec: AdminColumnFilterSpec = {
  param: "kind",
  mode: "multi",
  options: [
    { value: "a", label: "A" },
    { value: "b", label: "B" }
  ]
};

describe("parseFiltersFromParams", () => {
  it("drops values the column does not declare, so a hand-edited URL cannot send junk", () => {
    const params = new URLSearchParams("status=NONSENSE");
    expect(parseFiltersFromParams([statusSpec], params)).toEqual({});
  });

  it("keeps only the first value for a scalar param", () => {
    const params = new URLSearchParams("status=OPEN&status=PENDING");
    expect(parseFiltersFromParams([statusSpec], params)).toEqual({ status: ["OPEN"] });
  });

  it("keeps every value for a list param", () => {
    const params = new URLSearchParams("kind=a&kind=b");
    expect(parseFiltersFromParams([entitiesSpec], params)).toEqual({ kind: ["a", "b"] });
  });

  it("keeps the URL value while a catalogue-backed filter has no options yet", () => {
    const loading: AdminColumnFilterSpec = { param: "role", options: [] };
    const params = new URLSearchParams("role=support");
    expect(parseFiltersFromParams([loading], params)).toEqual({ role: ["support"] });
  });
});

describe("writeFiltersToParams", () => {
  it("clears a declared param that is no longer filtered and leaves foreign params alone", () => {
    const params = new URLSearchParams("status=OPEN&page=4&tournament=7");
    writeFiltersToParams([statusSpec], {}, params);
    expect(params.toString()).toBe("page=4&tournament=7");
  });

  it("repeats a list param once per value", () => {
    const params = new URLSearchParams();
    writeFiltersToParams([entitiesSpec], { kind: ["a", "b"] }, params);
    expect(params.getAll("kind")).toEqual(["a", "b"]);
  });
});

describe("serializeFilters", () => {
  it("is order-independent, so the table does not refetch on a reshuffled record", () => {
    expect(serializeFilters({ kind: ["b", "a"], status: ["OPEN"] })).toBe(
      serializeFilters({ status: ["OPEN"], kind: ["a", "b"] })
    );
  });

  it("treats an empty value list as no filter", () => {
    expect(serializeFilters({ status: [] })).toBe("");
  });
});
