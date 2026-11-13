import { type Tone } from "@craazzzyyfoxx/admin-kit/ui/tone";
import type { DateFormatter } from "@/components/kit/format-time";
import type { LogOperationErrorCode, LogProcessingRecord, LogProcessingStatus } from "@/types/admin.types";
import { LOG_OPERATION_ERROR_CODES, getRetryKind } from "../logs.helpers";

export type LogFilter = LogProcessingStatus;

/** Label key of every status; `tone` only where the row wants attention (a pill). */
export const STATUS_META: Record<LogProcessingStatus, { key: "queued" | "processing" | "awaitingLink" | "processed" | "failed"; tone?: Tone }> = {
  pending: { key: "queued" },
  processing: { key: "processing", tone: "info" },
  awaiting_link: { key: "awaitingLink", tone: "warning" },
  done: { key: "processed" },
  failed: { key: "failed", tone: "danger" }
};

/** Chip order is scan order: the states that need action come first. */
export const LOG_FILTERS: LogFilter[] = ["failed", "awaiting_link", "processing", "pending", "done"];

export const SOURCE_LABELS: Partial<Record<string, "sourceUpload" | "sourceDiscord" | "sourceManual" | "sourceHistoricalReference">> = {
  upload: "sourceUpload",
  discord: "sourceDiscord",
  manual: "sourceManual",
  historical_reference: "sourceHistoricalReference"
};

export function getRetryRefusal(record: LogProcessingRecord): "retryRawUnavailable" | "retryHistorical" | "retryUnbound" | null {
  if (!record.raw_available) return "retryRawUnavailable";
  if (record.source === "historical_reference") return "retryHistorical";
  if (record.status !== "awaiting_link" && record.attached_encounter_id != null && record.attached_encounter_game_id == null) {
    return "retryUnbound";
  }
  return null;
}

/**
 * Explicit bind: an awaiting or failed job whose stored document teams are known, with a verified raw source and
 * not a historical reference. Independent of the ordinary-retry refusals (`retryUnbound` reflects hints only).
 */
export function canBindExplicitly(record: LogProcessingRecord) {
  return (
    (record.status === "awaiting_link" || record.status === "failed") &&
    record.teams.length > 0 &&
    record.raw_available &&
    record.source !== "historical_reference"
  );
}

/** Done rows reparse (current evidence only); unfinished ones retry; nothing is offered while a source is refused. */
export function isRetryable(record: LogProcessingRecord) {
  return getRetryKind(record) != null && getRetryRefusal(record) == null;
}

/** Seconds between start and finish; null while unfinished or for a clock that went backwards. */
export function formatDuration(record: LogProcessingRecord) {
  if (!record.started_at || !record.finished_at) return null;
  const durationMs = new Date(record.finished_at).getTime() - new Date(record.started_at).getTime();
  if (!Number.isFinite(durationMs) || durationMs < 0) return null;
  return `${(durationMs / 1000).toFixed(1)}s`;
}

/** Matches `formatSyncTime` in ChallongeIntegrationSection so both admin logs read alike. */
export function formatLogTime(format: DateFormatter, value: string) {
  return format.dateTime(new Date(value), {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

/**
 * What the error column says first: a refused-operation code the catalogue
 * translates, otherwise the server's own message (HTTP status prefix dropped).
 * Historical text (code `historical`) reads as a plain message.
 */
export function getErrorSummary(
  record: LogProcessingRecord
): { code: LogOperationErrorCode } | { message: string } | null {
  const structured = record.error && record.error.code !== "historical" ? record.error : null;
  const errorMessage = record.error_message;
  if (!structured && !errorMessage) return null;

  const rawCode = structured?.code ?? errorMessage?.match(/['"]code['"]:\s*['"]([^'"]+)['"]/)?.[1];
  const code = LOG_OPERATION_ERROR_CODES.find((known) => known === rawCode);
  if (code) return { code };
  const message = structured?.message || errorMessage || "";
  return { message: message.replace(/^(\d{3}:\s*)?/, "").slice(0, 120) };
}

/** The message plus every issue path the validator reported. */
export function getErrorDetail(record: LogProcessingRecord) {
  const issues = record.error && record.error.code !== "historical" ? record.error.issues : [];
  return [record.error_message, ...issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`)]
    .filter(Boolean)
    .join("\n");
}
