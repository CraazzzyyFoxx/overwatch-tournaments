"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, HelpCircle } from "lucide-react";
import { useFormatter } from "next-intl";

import { StatusPill } from "@/components/kit/StatusPill";
import { EYEBROW_CLASS, TONE_CLASS, type Tone } from "@/components/kit/tone";
import { formatDate } from "@/components/kit/format-time";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { AdminMatchRow, LogProcessingStatus } from "@/types/admin.types";

const STATUS_TONE: Record<LogProcessingStatus, Tone> = {
  pending: "neutral",
  processing: "info",
  done: "success",
  failed: "danger"
};

function Field({ label, value }: Readonly<{ label: string; value: string | number }>) {
  return (
    <div className="min-w-0">
      <p className={EYEBROW_CLASS}>{label}</p>
      <p className="truncate text-sm tabular-nums">{value}</p>
    </div>
  );
}

/**
 * Technical summary for one parsed map, with its provenance.
 *
 * The provenance block is the reason this exists: `Encounter.has_logs` said a
 * log existed somewhere, never which upload produced which map. Since
 * `mtchlog001` that is a foreign key rather than a filename comparison, so the
 * answer is either a specific record or an honest "unresolved" — this never
 * guesses.
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
  const format = useFormatter();
  const detailQuery = useQuery({
    queryKey: ["admin-matches", "detail", row.id, workspaceId],
    queryFn: () => adminService.getAdminMatch(row.id, workspaceId!),
    enabled: workspaceId != null
  });

  const detail = detailQuery.data;
  const record = row.log_record;
  const minutes = Math.floor(row.time / 60);
  const seconds = Math.round(row.time % 60);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <Field
          label="Score"
          value={`${row.home_team.name ?? "?"} ${row.home_score} – ${row.away_score} ${row.away_team.name ?? "?"}`}
        />
        <Field label="Duration" value={`${minutes}m ${String(seconds).padStart(2, "0")}s`} />
        <Field label="Match code" value={row.code ?? "—"} />
        <Field label="Rounds" value={detailQuery.isLoading ? "…" : (detail?.rounds ?? "—")} />
      </div>

      <section className="rounded-xl border border-border/60 p-3">
        <p className={EYEBROW_CLASS}>Provenance</p>
        {record ? (
          <div className="mt-2 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill tone={STATUS_TONE[record.status]}>{record.status}</StatusPill>
              <span className="font-mono text-xs">{record.filename}</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Record" value={`#${record.id}`} />
              <Field label="Source" value={record.source ?? "—"} />
              <Field label="Uploader" value={record.uploader_id ?? "—"} />
              <Field label="Attempts" value={record.attempts} />
              <Field label="Started" value={formatDate(format, record.started_at)} />
              <Field label="Finished" value={formatDate(format, record.finished_at)} />
            </div>
            {record.error_message ? (
              <p
                className={cn(
                  "flex items-start gap-2 rounded-md border p-2 text-xs",
                  TONE_CLASS.danger
                )}
              >
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                <span className="break-all">{record.error_message}</span>
              </p>
            ) : null}
          </div>
        ) : (
          // Not an error state. The ingestion table postdates most parsed
          // matches, so the overwhelming majority of history lands here and
          // dressing it as a failure would bury the ones that really failed.
          <div className="mt-2 space-y-1">
            <p className="flex items-center gap-2 text-sm">
              <HelpCircle className="size-4 text-muted-foreground" aria-hidden />
              Provenance unresolved
            </p>
            <p className="text-xs text-muted-foreground">
              No ingestion record is linked to this map. Matches parsed before the ingestion table
              existed have none — the backfill left them unlinked rather than guessing from the
              filename.
            </p>
            <p className="font-mono text-xs text-muted-foreground">{row.log_name}</p>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-border/60 p-3">
        <p className={EYEBROW_CLASS}>Parsed volume</p>
        {detailQuery.isLoading ? (
          <Skeleton className="mt-2 h-10 w-full" />
        ) : (
          <div className="mt-2 grid grid-cols-3 gap-2">
            <Field label="Statistics" value={detail?.statistics_count ?? 0} />
            <Field label="Kill feed" value={detail?.kill_feed_count ?? 0} />
            <Field label="Events" value={detail?.event_count ?? 0} />
          </div>
        )}
        {detail != null && detail.statistics_count === 0 ? (
          // A map with no statistics parsed but a `done` record means the log
          // was accepted and yielded nothing — worth surfacing, since the
          // encounter will still count it as played.
          <p className="mt-2 text-xs text-warning">
            No player statistics were written for this map.
          </p>
        ) : null}
      </section>
    </div>
  );
}
