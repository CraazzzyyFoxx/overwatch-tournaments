import { TintedBadge } from "@/components/admin/TintedBadge";
import type { Tone } from "@/components/admin/tone";
import type { RankCollectionStats } from "@/types/admin.types";

export { formatDate, formatInterval, formatRelative } from "@/components/admin/format-time";

/** Tone per fetch status, handed to `TintedBadge` as the domain's vocabulary. */
const STATUS_TONES: Record<string, Tone> = {
  ok: "success",
  private: "warning",
  not_found: "warning",
  error: "danger",
  rate_limited: "warning",
  disabled: "neutral",
  pending: "info"
};

/**
 * Solid fill per status, for the stacked distribution bar. The three warning
 * statuses share one hue, so they are separated by alpha instead of by three
 * unrelated palette colours.
 */
export const STATUS_BAR: Record<string, string> = {
  ok: "bg-success",
  pending: "bg-info",
  not_found: "bg-warning",
  private: "bg-warning/70",
  error: "bg-danger",
  rate_limited: "bg-warning/40",
  disabled: "bg-muted-foreground/40"
};

/** Canonical display order for statuses. */
export const STATUS_ORDER = [
  "ok",
  "pending",
  "not_found",
  "private",
  "error",
  "rate_limited",
  "disabled"
] as const;

export function StatusBadge({ status }: Readonly<{ status: string | null }>) {
  return <TintedBadge value={status} tones={STATUS_TONES} fallback="never" />;
}

/** Collection is considered stalled once the newest capture is this old. */
export const RANK_STALE_AFTER_MS = 30 * 60 * 1000;

/**
 * Is battle-tag parsing actually down right now?
 *
 * Two ways it dies quietly, neither of which shows up in `error_rate_24h`:
 * an open circuit means every fetch is refused before it leaves the worker, so
 * `fetch_log` simply stops growing and the error ratio *falls*; and a stalled
 * collector writes nothing at all, which no ratio over an empty window can see.
 * The September 2026 OverFast DNS outage was exactly this — the dashboard stayed
 * green for a day while nothing was collected.
 */
export function rankParsingOutage(
  stats: RankCollectionStats,
  now: number = Date.now()
): { reason: "circuit_open" | "stale"; staleMs: number } | null {
  if (!stats.enabled) return null;
  const last = stats.last_success_at ? Date.parse(stats.last_success_at) : Number.NaN;
  const staleMs = Number.isNaN(last) ? Number.POSITIVE_INFINITY : now - last;
  if (stats.overfast_circuit_state === "open") return { reason: "circuit_open", staleMs };
  // "Never succeeded" is not staleness: a freshly seeded collector has nothing
  // to be late with, and the tab already reads "never". The Prometheus rule
  // RankCollectionNeverSucceeded owns that case, with a 30m grace period.
  if (Number.isNaN(last)) return null;
  if (staleMs > RANK_STALE_AFTER_MS) return { reason: "stale", staleMs };
  return null;
}

/**
 * Health marker for the Rank tab of the collectors bar (F14).
 *
 * Ordered by what the operator must act on first: a paused collector explains
 * every other number on the page, a dead upstream outranks a bad error ratio
 * (it is why there is no ratio to read), and a fleet-wide error rate outranks a
 * handful of tags the worker gave up on. The word is not decoration — the tab
 * renders it `sr-only`, because a dot alone encodes state in colour.
 */
export function rankHealthDot(stats: RankCollectionStats): { tone: Tone; label: string } {
  if (!stats.enabled) return { tone: "neutral", label: "Paused" };
  if (rankParsingOutage(stats)) return { tone: "danger", label: "Failing" };
  if ((stats.error_rate_24h ?? 0) >= 0.2) return { tone: "danger", label: "Failing" };
  if ((stats.by_status?.disabled ?? 0) > 0) return { tone: "warning", label: "Degraded" };
  return { tone: "success", label: "Healthy" };
}
