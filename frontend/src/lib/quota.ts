import { ApiError, errorBodyFields } from "@/lib/api-error";
import { QUOTA_DIMENSIONS, type QuotaDimension } from "@/types/auth.types";

/**
 * A quota override write refused because it would raise a ceiling the caller is
 * only allowed to lower (`code=quota_above_inherited`, HTTP 422).
 *
 * `limit` is what the row would inherit — `null` when the inherited value is
 * itself unlimited, which is why "above unlimited" is reported as a ceiling of
 * nothing rather than as a number.
 */
export interface QuotaAboveInherited {
  dimension: QuotaDimension;
  limit: number | null;
  requested: number | null;
}

const IS_DIMENSION: Record<string, true> = Object.fromEntries(
  QUOTA_DIMENSIONS.map((dimension) => [dimension, true])
);

/**
 * Read a `quota_above_inherited` rejection off a thrown value, so the screen can
 * mark the offending input instead of showing a toast that says nothing about
 * which of the five numbers was refused.
 *
 * Returns `null` for every other failure — including a 422 naming a dimension
 * this build does not know, which must not be pinned on an unrelated field.
 */
export function parseQuotaAboveInherited(error: unknown): QuotaAboveInherited | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null;

  for (const field of errorBodyFields(error.body)) {
    if (field.code !== "quota_above_inherited") continue;
    const dimension = field.limit_name;
    if (typeof dimension !== "string" || !IS_DIMENSION[dimension]) return null;
    return {
      dimension: dimension as QuotaDimension,
      limit: typeof field.limit === "number" ? field.limit : null,
      requested: typeof field.requested === "number" ? field.requested : null
    };
  }
  return null;
}
