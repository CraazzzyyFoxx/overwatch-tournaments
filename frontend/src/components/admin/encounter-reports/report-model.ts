import type { DateFormatter } from "@/components/kit/format-time";
import type { AdminCaptainReport } from "@/types/admin.types";

/** What an empty cell renders as, everywhere on this screen. */
export const DASH = "—";

/** Lobby codes in play order — the report stores them unordered. */
export function mapCodes(report: AdminCaptainReport | null): string {
  if (!report || report.map_codes.length === 0) return "";
  return [...report.map_codes]
    .sort((a, b) => a.map_index - b.map_index)
    .map((entry) => `M${entry.map_index + 1} ${entry.code}`)
    .join(", ");
}

/** What the captain last stood behind: an edited report supersedes its filing. */
export function submittedAt(report: AdminCaptainReport | null): string | null {
  return report ? (report.updated_at ?? report.created_at) : null;
}

export function fmtDate(format: DateFormatter, value: string | null | undefined): string {
  return value ? format.dateTime(new Date(value), { dateStyle: "medium", timeStyle: "short" }) : DASH;
}
