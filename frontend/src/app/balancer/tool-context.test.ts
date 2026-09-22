import { describe, expect, test } from "vitest";

import { ApiError } from "@/lib/api/error";

import { resolveToolState, type SummaryQuerySnapshot } from "./tool-context";

const summary = { id: 5, name: "Cup", status: "registration", workspace_id: 2 };

function snapshot(partial: Partial<SummaryQuerySnapshot> = {}): SummaryQuerySnapshot {
  return { data: undefined, isError: false, error: null, ...partial };
}

describe("resolveToolState", () => {
  test("missing when there is no ?tournament= param", () => {
    expect(resolveToolState(null, snapshot())).toBe("missing");
  });

  test("missing wins even if a stale query result is present", () => {
    expect(resolveToolState(null, snapshot({ data: summary }))).toBe("missing");
  });

  test("loading while the summary query has neither data nor error", () => {
    expect(resolveToolState(5, snapshot())).toBe("loading");
  });

  test("ready when the summary is loaded", () => {
    expect(resolveToolState(5, snapshot({ data: summary }))).toBe("ready");
  });

  test("forbidden on 403", () => {
    const error = new ApiError(403, [{ msg: "forbidden", code: "forbidden" }]);
    expect(resolveToolState(5, snapshot({ isError: true, error }))).toBe("forbidden");
  });

  test("forbidden on 401", () => {
    const error = new ApiError(401, [{ msg: "unauthorized", code: "unauthorized" }]);
    expect(resolveToolState(5, snapshot({ isError: true, error }))).toBe("forbidden");
  });

  test("not_found on 404", () => {
    const error = new ApiError(404, [{ msg: "not found", code: "not_found" }]);
    expect(resolveToolState(5, snapshot({ isError: true, error }))).toBe("not_found");
  });

  test("not_found on 400 with a not_found detail code", () => {
    const error = new ApiError(400, [{ msg: "Tournament not found", code: "not_found" }]);
    expect(resolveToolState(5, snapshot({ isError: true, error }))).toBe("not_found");
  });

  test("unexpected errors fall back to not_found (pointer screen)", () => {
    expect(
      resolveToolState(5, snapshot({ isError: true, error: new Error("network down") }))
    ).toBe("not_found");
  });
});
