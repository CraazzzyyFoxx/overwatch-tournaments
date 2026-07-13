import { Badge } from "@/components/ui/badge";

/** Tailwind classes per RankCollectionStatus for badges (border+tint+text). */
export const STATUS_STYLES: Record<string, string> = {
  ok: "border-emerald-500/20 bg-emerald-500/10 text-emerald-300",
  private: "border-amber-500/20 bg-amber-500/10 text-amber-300",
  not_found: "border-amber-500/20 bg-amber-500/10 text-amber-300",
  error: "border-rose-500/20 bg-rose-500/10 text-rose-300",
  rate_limited: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  disabled: "border-white/10 bg-white/5 text-white/50",
  pending: "border-sky-500/20 bg-sky-500/10 text-sky-300"
};

/** Solid fill per status, for the stacked distribution bar. */
export const STATUS_BAR: Record<string, string> = {
  ok: "bg-emerald-500",
  pending: "bg-sky-500",
  not_found: "bg-amber-500",
  private: "bg-amber-400",
  error: "bg-rose-500",
  rate_limited: "bg-orange-500",
  disabled: "bg-white/25"
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

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

/** Compact "5m ago" / "2h ago" style relative time; falls back to "—". */
export function formatRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const diffSec = Math.round((Date.now() - date.getTime()) / 1000);
  if (diffSec < 60) return "just now";
  const mins = Math.round(diffSec / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function StatusBadge({ status }: { status: string | null }) {
  return (
    <Badge
      variant="outline"
      className={STATUS_STYLES[status ?? ""] ?? "border-white/10 bg-white/5 text-white/50"}
    >
      {status ?? "never"}
    </Badge>
  );
}
