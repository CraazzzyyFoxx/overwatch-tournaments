import type { QuotaDimension, QuotaLimitsPayload, QuotaScopeUsage } from "@/types/auth.types";

/**
 * The three counted dimensions and where a usage row keeps their spend and
 * their window.
 *
 * `concurrent_heavy` has no window: a slot is freed when the job ends (or when
 * its reservation expires), so there is nothing to count down to.
 */
export const QUOTA_COUNTERS: readonly {
  dimension: QuotaDimension;
  used: keyof QuotaScopeUsage;
  resetIn: keyof QuotaScopeUsage | null;
}[] = [
  { dimension: "requests_per_minute", used: "requests_used", resetIn: "requests_reset_in" },
  { dimension: "heavy_per_day", used: "heavy_used", resetIn: "heavy_reset_in" },
  { dimension: "concurrent_heavy", used: "concurrent_used", resetIn: null }
];

/** Per-request caps: a ceiling on one call, never a running counter. */
export const QUOTA_CAPS = [
  "max_upload_bytes",
  "max_items_per_request"
] as const satisfies readonly QuotaDimension[];

/**
 * A draft override row. Every dimension is present and `null` means inherit, so
 * an emptied field is a deliberate "inherit again" rather than an absent key
 * the form would silently keep at its old value.
 */
export type QuotaLimitsDraft = Record<QuotaDimension, number | null>;

export const EMPTY_QUOTA_LIMITS: QuotaLimitsDraft = {
  requests_per_minute: null,
  heavy_per_day: null,
  concurrent_heavy: null,
  max_upload_bytes: null,
  max_items_per_request: null
};

/** True once at least one dimension carries a number, i.e. the row exists. */
export function hasQuotaOverride(limits: QuotaLimitsPayload): boolean {
  return (
    limits.requests_per_minute != null ||
    limits.heavy_per_day != null ||
    limits.concurrent_heavy != null ||
    limits.max_upload_bytes != null ||
    limits.max_items_per_request != null
  );
}
