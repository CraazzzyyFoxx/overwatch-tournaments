"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { InspectorField, InspectorSection } from "@/components/kit/InspectorField";
import { StatusPill } from "@/components/kit/StatusPill";
import type { Tone } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { formatDate } from "@/components/kit/format-time";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import adminService from "@/services/admin.service";
import { observedScore } from "@/lib/encounter/detail";
import { seatsBySlot } from "@/lib/encounter/seats";
import type { AdminMatchRow, LogProcessingStatus } from "@/types/admin.types";
import { adminQueryKeys } from "@/lib/admin/query-keys";

/**
 * The ingestion states that want an admin, and their tone. `done` is what
 * nearly every map is, so it has no pill: its absence says the log went
 * through.
 */
const LOG_STATUS_ATTENTION: Partial<Record<LogProcessingStatus, Tone>> = {
  pending: "neutral",
  processing: "info",
  awaiting_link: "warning",
  failed: "danger"
};

/** A parsed map's ingestion state as a pill, only while it is not `done`. */
export function LogStatusPill({ status }: Readonly<{ status: LogProcessingStatus }>) {
  const t = useTranslations("adminMatches.parsed");
  const tone = LOG_STATUS_ATTENTION[status];
  return tone ? <StatusPill tone={tone}>{t(status)}</StatusPill> : null;
}

/**
 * Technical summary for one parsed map, with its provenance.
 *
 * The linked ingestion job identifies the raw log. A missing job means the
 * raw log is unavailable; never infer provenance from a filename.
 *
 * It renders the body only. The surrounding panel-or-sheet is `Inspector`,
 * which is where every T2 browser puts row detail; this used to own a `Sheet`
 * of its own, which meant the table was covered on a wide screen instead of
 * simply narrowing beside the detail.
 *
 * The row supplies everything the list already knows; only the aggregates are
 * fetched, and only while the detail is open.
 */
export function ParsedMatchDetail({
  row,
  workspaceId
}: Readonly<{
  row: AdminMatchRow;
  workspaceId: number | null;
}>) {
  const t = useTranslations("adminMatches.parsed");
  const format = useFormatter();
  const detailQuery = useQuery({
    queryKey: adminQueryKeys.matchDetail(row.id, workspaceId),
    queryFn: () => adminService.getAdminMatch(row.id, workspaceId!),
    enabled: workspaceId != null
  });

  const detail = detailQuery.data;
  const record = row.log_record;
  const duration =
    row.duration_s == null
      ? null
      : `${Math.floor(row.duration_s / 60)}m ${String(Math.round(row.duration_s % 60)).padStart(2, "0")}s`;
  const seats = seatsBySlot(row.participants);
  const scores = seats.map((seat) => observedScore(seat));
  const score = scores.some((value) => value == null)
    ? null
    : seats.length === 2
      ? `${seats[0].name} ${scores[0]} – ${scores[1]} ${seats[1].name}`
      : seats.map((seat, index) => `${seat.name} ${scores[index]}`).join(" – ");

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <InspectorField label={t("score")}>
          {score ? <span className="tabular-nums">{score}</span> : null}
        </InspectorField>
        <InspectorField label={t("duration")}>
          {duration ? <span className="tabular-nums">{duration}</span> : null}
        </InspectorField>
        <InspectorField label={t("rounds")}>
          {detailQuery.isLoading ? (
            <Skeleton className="h-4 w-8" />
          ) : detail?.rounds == null ? null : (
            <span className="tabular-nums">{detail.rounds}</span>
          )}
        </InspectorField>
      </div>

      <InspectorSection title={t("provenance")}>
        {record ? (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <LogStatusPill status={record.status} />
              {record.filename ? <span className="font-mono text-xs">{record.filename}</span> : null}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <InspectorField label={t("record")}>
                <span className="tabular-nums">#{record.id}</span>
              </InspectorField>
              <InspectorField label={t("source")}>{record.source}</InspectorField>
              <InspectorField label={t("uploader")}>
                {record.uploader_id == null ? null : <span className="tabular-nums">{record.uploader_id}</span>}
              </InspectorField>
              <InspectorField label={t("attempts")}>
                <span className="tabular-nums">{record.attempts}</span>
              </InspectorField>
              <InspectorField label={t("started")}>
                {record.started_at ? formatDate(format, record.started_at) : null}
              </InspectorField>
              <InspectorField label={t("finished")}>
                {record.finished_at ? formatDate(format, record.finished_at) : null}
              </InspectorField>
            </div>
            {record.error_message ? (
              <p className="break-all text-xs text-danger">{record.error_message}</p>
            ) : null}
          </div>
        ) : (
          // No linked raw log is distinct from a failed ingestion job.
          <p className="text-sm text-muted-foreground">{t("provenanceText")}</p>
        )}
      </InspectorSection>

      <InspectorSection title={t("parsedVolume")}>
        {detailQuery.isLoading ? (
          <Skeleton className="h-10 w-full" />
        ) : (
          <div className="grid grid-cols-3 gap-2">
            <InspectorField label={t("statistics")}>
              <span className="tabular-nums">{detail?.statistics_count ?? 0}</span>
            </InspectorField>
            <InspectorField label={t("killFeed")}>
              <span className="tabular-nums">{detail?.kill_feed_count ?? 0}</span>
            </InspectorField>
            <InspectorField label={t("events")}>
              <span className="tabular-nums">{detail?.event_count ?? 0}</span>
            </InspectorField>
          </div>
        )}
        {detail != null && detail.statistics_count === 0 ? (
          // A map with no statistics parsed but a `done` record means the log
          // was accepted and yielded nothing — worth surfacing, since the
          // encounter will still count it as played.
          <p className="mt-2 text-xs text-warning">{t("noStats")}</p>
        ) : null}
      </InspectorSection>
    </div>
  );
}
