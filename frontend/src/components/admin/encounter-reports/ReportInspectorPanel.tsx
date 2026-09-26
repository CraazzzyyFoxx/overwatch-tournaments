"use client";

import { AdminReportPairCell } from "@/components/admin/AdminReportPairCell";
import { EYEBROW_CLASS, TONE_TEXT } from "@/components/kit/tone";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { EncounterReportsRow } from "@/types/admin.types";
import type { ReportCustomFieldDefinition } from "@/types/encounter.types";

import { ReportDetail } from "./ReportDetail";
import { fmtDate } from "./report-model";

/**
 * One encounter's whole filing, not a summary of it: this is the surface an
 * admin adjudicates from, and a field left out here is a field they would have
 * to go find in the database.
 */
export function ReportInspectorPanel({
  row,
  customFields
}: Readonly<{
  row: EncounterReportsRow;
  customFields: ReportCustomFieldDefinition[];
}>) {
  const format = useFormatter();

  return (
    <div className="space-y-4">
      <AdminReportPairCell
        homeReport={row.home_report}
        awayReport={row.away_report}
        scoresMatch={row.scores_match}
        seriesScoreValid={row.series_score_valid}
      />

      <ReportDetail
        label="Home"
        teamName={row.home_team?.name ?? "?"}
        report={row.home_report}
        customFields={customFields}
      />
      <ReportDetail
        label="Away"
        teamName={row.away_team?.name ?? "?"}
        report={row.away_report}
        customFields={customFields}
      />

      <div className="grid grid-cols-2 gap-3">
        <div className="min-w-0">
          <p className={EYEBROW_CLASS}>Recorded teams</p>
          <p className="truncate text-sm">
            {row.home_team?.name ?? "?"} vs {row.away_team?.name ?? "?"}
          </p>
        </div>
        <div className="min-w-0">
          <p className={EYEBROW_CLASS}>Result</p>
          <p className="truncate text-sm">{row.result_status}</p>
        </div>
        <div className="min-w-0">
          <p className={EYEBROW_CLASS}>Encounter status</p>
          <p className="truncate text-sm">{row.status}</p>
        </div>
        <div className="min-w-0">
          <p className={EYEBROW_CLASS}>Reports filed</p>
          <p className="truncate text-sm tabular-nums">{row.reported_count}/2</p>
        </div>
        <div className="min-w-0">
          <p className={EYEBROW_CLASS}>Scheduled</p>
          <p className="truncate text-sm tabular-nums">{fmtDate(format, row.scheduled_at)}</p>
        </div>
        <div className="min-w-0">
          <p className={EYEBROW_CLASS}>Series check</p>
          <p className={cn("truncate text-sm", !row.series_score_valid && TONE_TEXT.warning)}>
            {row.series_score_valid ? "Within best-of" : "Score outside best-of"}
          </p>
        </div>
        <div className="min-w-0">
          <p className={EYEBROW_CLASS}>Encounter ID</p>
          <p className="truncate text-sm tabular-nums">{row.id}</p>
        </div>
        <div className="min-w-0">
          <p className={EYEBROW_CLASS}>Tournament</p>
          <p className="truncate text-sm">{row.tournament_name ?? `#${row.tournament_id}`}</p>
        </div>
      </div>

      {row.last_resolution ? (
        <section className="rounded-xl border border-border/60 p-3">
          <p className={EYEBROW_CLASS}>Last resolution</p>
          <p className="mt-1 text-sm">
            {row.last_resolution.action} by{" "}
            {row.last_resolution.actor_name ?? "an automated process"}
          </p>
          <p className="text-xs tabular-nums text-muted-foreground">
            {fmtDate(format, row.last_resolution.created_at)}
          </p>
        </section>
      ) : null}
    </div>
  );
}
