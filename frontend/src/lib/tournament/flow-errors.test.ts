import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/error";

import { flowErrorCode } from "./flow-errors";

describe("flowErrorCode", () => {
  it("names a known flow refusal", () => {
    const error = new ApiError(409, [{ code: "formation_not_forming", msg: "Formation node 12 is 'draft', not forming" }]);
    expect(flowErrorCode(error)).toBe("formation_not_forming");
  });

  it("is null for an unknown code and for a value that is not an API error", () => {
    expect(flowErrorCode(new ApiError(409, [{ code: "something_else", msg: "x" }]))).toBeNull();
    expect(flowErrorCode(new Error("boom"))).toBeNull();
  });
});
