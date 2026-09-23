import { describe, expect, it } from "bun:test";

import { ApiError } from "@/lib/api/error";
import { parseQuotaAboveInherited } from "@/lib/auth/quota";

/**
 * The point of this file: a `quota_above_inherited` refusal must reach the form
 * as "this dimension, this ceiling", whichever envelope carried it.
 *
 * The machine fields ride `details.fields[0]`, and the two API versions put
 * that object in different places: v1 spreads the envelope's `details` next to
 * `detail`/`code`, v2 nests the whole envelope under `error.details`. Reading
 * only one of them is how a per-field error silently degrades into a toast that
 * names none of the five numbers.
 */

const FIELD = {
  field: null,
  msg: "quota above inherited",
  code: "quota_above_inherited",
  limit_name: "heavy_per_day",
  limit: 500,
  requested: 5000,
};

function apiError(status: number, body: unknown) {
  return new ApiError(status, [{ msg: "quota above inherited", code: "unprocessable" }], body);
}

describe("parseQuotaAboveInherited", () => {
  it("reads the v1 body, where fields sits next to detail", () => {
    const rejection = parseQuotaAboveInherited(
      apiError(422, { detail: "quota above inherited", code: "unprocessable", fields: [FIELD] }),
    );
    expect(rejection).toEqual({ dimension: "heavy_per_day", limit: 500, requested: 5000 });
  });

  it("reads the v2 body, where fields sits under error.details", () => {
    const rejection = parseQuotaAboveInherited(
      apiError(422, {
        ok: false,
        error: { code: "unprocessable", message: "…", details: { fields: [FIELD] } },
      }),
    );
    expect(rejection).toEqual({ dimension: "heavy_per_day", limit: 500, requested: 5000 });
  });

  it("keeps an unlimited inherited ceiling as null, not as zero", () => {
    // `limit: null` means the inherited value is itself unlimited, so *any*
    // number raises it. Coercing that to 0 would claim the opposite.
    const rejection = parseQuotaAboveInherited(
      apiError(422, { fields: [{ ...FIELD, limit: null }] }),
    );
    expect(rejection).toEqual({ dimension: "heavy_per_day", limit: null, requested: 5000 });
  });

  it("refuses to pin a dimension it does not know on some other field", () => {
    expect(
      parseQuotaAboveInherited(apiError(422, { fields: [{ ...FIELD, limit_name: "gpu_hours" }] })),
    ).toBeNull();
  });

  it("ignores every other failure, including the 429 the same gate raises", () => {
    expect(parseQuotaAboveInherited(apiError(422, { detail: "name is required" }))).toBeNull();
    expect(
      parseQuotaAboveInherited(
        apiError(429, { fields: [{ code: "quota_exceeded", limit_name: "heavy_per_day" }] }),
      ),
    ).toBeNull();
    expect(parseQuotaAboveInherited(new Error("boom"))).toBeNull();
  });
});
