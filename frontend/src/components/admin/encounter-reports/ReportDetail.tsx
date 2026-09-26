"use client";

import { EYEBROW_CLASS } from "@/components/kit/tone";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { AdminCaptainReport } from "@/types/admin.types";
import type { ReportCustomFieldDefinition } from "@/types/encounter.types";

import { DASH, fmtDate, mapCodes, submittedAt } from "./report-model";

/**
 * Everything one captain filed, in full.
 *
 * The table cell is a summary by necessity; this is the surface an admin
 * settling a dispute reads, so it withholds nothing the report carries —
 * including the organizer's own questions, whose labels come from the
 * tournament's report form rather than the raw storage keys.
 */
export function ReportDetail({
  label,
  teamName,
  report,
  customFields
}: Readonly<{
  label: string;
  teamName: string;
  report: AdminCaptainReport | null;
  customFields: ReportCustomFieldDefinition[];
}>) {
  const format = useFormatter();
  if (!report) {
    return (
      <section className="rounded-xl border border-dashed border-border/60 p-3">
        <p className={EYEBROW_CLASS}>
          {label} · {teamName}
        </p>
        <p className="mt-1 text-sm italic text-muted-foreground">No report filed.</p>
      </section>
    );
  }

  // Answers to questions the form no longer defines still happened, so they are
  // listed under their key rather than dropped with the definition.
  const known = new Set(customFields.map((field) => field.key));
  const extras = Object.entries(report.custom_fields).filter(([key]) => !known.has(key));
  const codes = mapCodes(report);

  return (
    <section className="space-y-2 rounded-xl border border-border/60 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <p className={EYEBROW_CLASS}>
          {label} · {teamName}
        </p>
        <p className="font-mono text-sm font-semibold tabular-nums">
          {report.home_score} &ndash; {report.away_score}
        </p>
      </div>

      <dl className="space-y-1 text-sm">
        <Field label="Reported by" value={report.reporter_name ?? "unknown"} />
        <Field label="Submitted" value={fmtDate(format, submittedAt(report))} mono />
        <Field
          label="Closeness"
          value={report.closeness == null ? "not rated" : `${report.closeness}/10`}
        />
        {codes ? <Field label="Lobby codes" value={codes} mono /> : null}
        {report.comment ? <Field label="Comment" value={report.comment} /> : null}
        {customFields.map((field) => (
          <Field
            key={field.key}
            label={field.label}
            value={report.custom_fields[field.key] || DASH}
          />
        ))}
        {extras.map(([key, value]) => (
          <Field key={key} label={key} value={value} />
        ))}
      </dl>
    </section>
  );
}

function Field({
  label,
  value,
  mono
}: Readonly<{ label: string; value: string; mono?: boolean }>) {
  return (
    <div className="grid grid-cols-[9rem_minmax(0,1fr)] gap-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("min-w-0 break-words", mono && "font-mono text-xs tabular-nums")}>
        {value}
      </dd>
    </div>
  );
}
