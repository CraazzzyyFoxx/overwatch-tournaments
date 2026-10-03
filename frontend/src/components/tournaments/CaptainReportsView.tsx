"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type {
  CaptainReport,
  Encounter,
  MatchReportForm,
  ReportCustomFieldDefinition,
} from "@/types/encounter.types";

interface CaptainReportsViewProps {
  encounter: Encounter;
  reports: CaptainReport[];
  /**
   * Only supplies labels for custom answers. Absent (or missing a definition an
   * older report answered) falls back to the raw key, so a field the organizer
   * has since renamed or removed still reads rather than vanishing.
   */
  form?: MatchReportForm;
  className?: string;
}

/** One side's report: by `side`, falling back to the team for a report filed before sides were stored. */
export function pickReport(
  reports: CaptainReport[],
  side: "home" | "away",
  teamId: number
): CaptainReport | null {
  return (
    reports.find((report) => report.side === side) ??
    reports.find((report) => report.team_id === teamId) ??
    null
  );
}

function ReportCard({
  title,
  teamName,
  report,
  customFields,
}: Readonly<{
  title: string;
  teamName: string;
  report: CaptainReport | null;
  customFields: ReportCustomFieldDefinition[];
}>) {
  const t = useTranslations();
  const comment = report?.comment?.trim();
  const customAnswers = Object.entries(report?.custom_fields ?? {}).filter(
    ([, value]) => value.trim().length > 0
  );

  return (
    <div className="rounded-xl border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-3">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-label font-bold uppercase tracking-[0.15em] text-[color:var(--aqt-fg-dim)]">{title}</p>
        <p className="truncate text-xs font-semibold text-[color:var(--aqt-fg-muted)]">{teamName}</p>
      </div>
      {report ? (
        <div className="mt-2 space-y-1.5 text-sm text-[color:var(--aqt-fg-muted)]">
          <div className="text-base font-bold text-[color:var(--aqt-fg)]">
            {report.home_score} - {report.away_score}
          </div>
          <div className="text-xs text-[color:var(--aqt-fg-muted)]">
            {t("matchReport.matchQuality")}:{" "}
            {report.closeness != null ? `${report.closeness}/10` : "—"}
          </div>
          {report.map_codes.length > 0 && (
            <ul className="mt-1 space-y-0.5">
              {report.map_codes
                .slice()
                .sort((a, b) => a.map_index - b.map_index)
                .map((mapCode) => (
                  <li key={mapCode.id} className="flex items-center gap-2 text-xs text-[color:var(--aqt-fg-muted)]">
                    <span className="text-[color:var(--aqt-fg-dim)]">
                      {t("matchReport.mapLabel", { index: String(mapCode.map_index) })}
                    </span>
                    <span className="text-[color:var(--aqt-fg-muted)]">{mapCode.code}</span>
                  </li>
                ))}
            </ul>
          )}
          {comment ? (
            <div className="mt-1">
              <p className="text-label font-bold uppercase tracking-[0.15em] text-[color:var(--aqt-fg-dim)]">
                {t("matchReport.comment")}
              </p>
              <p className="mt-0.5 whitespace-pre-wrap break-words text-xs text-[color:var(--aqt-fg-muted)]">
                {comment}
              </p>
            </div>
          ) : null}
          {customAnswers.length > 0 && (
            <dl className="mt-1 space-y-1">
              {customAnswers.map(([key, value]) => (
                <div key={key}>
                  <dt className="text-label font-bold uppercase tracking-[0.15em] text-[color:var(--aqt-fg-dim)]">
                    {customFields.find((field) => field.key === key)?.label ?? key}
                  </dt>
                  <dd className="mt-0.5 whitespace-pre-wrap break-words text-xs text-[color:var(--aqt-fg-muted)]">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      ) : (
        <p className="mt-2 text-xs italic text-[color:var(--aqt-fg-dim)]">{t("matchReport.noReportYet")}</p>
      )}
    </div>
  );
}

export function CaptainReportsView({
  encounter,
  reports,
  form,
  className,
}: Readonly<CaptainReportsViewProps>) {
  const t = useTranslations();
  const homeReport = pickReport(reports, "home", encounter.home_team_id);
  const awayReport = pickReport(reports, "away", encounter.away_team_id);
  const homeLabel = encounter.home_team?.name?.trim() || t("common.homeTeam");
  const awayLabel = encounter.away_team?.name?.trim() || t("common.awayTeam");
  const customFields = form?.custom_fields ?? [];
  // Averaging needs both ratings; one unrated side makes the average a lie, not
  // a smaller number.
  const avgCloseness =
    homeReport?.closeness != null && awayReport?.closeness != null
      ? (homeReport.closeness + awayReport.closeness) / 2
      : null;

  return (
    <div className={cn("space-y-2", className)}>
      <p className="text-label font-bold uppercase tracking-[0.15em] text-[color:var(--aqt-fg-dim)]">
        {t("matchReport.bothReportsTitle")}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <ReportCard
          title={t("matchReport.homeReport")}
          teamName={homeLabel}
          report={homeReport}
          customFields={customFields}
        />
        <ReportCard
          title={t("matchReport.awayReport")}
          teamName={awayLabel}
          report={awayReport}
          customFields={customFields}
        />
      </div>
      {avgCloseness != null && (
        <p className="text-xs text-[color:var(--aqt-fg-muted)]">
          {t("matchReport.avgCloseness")}: {avgCloseness.toFixed(1)}/10
        </p>
      )}
    </div>
  );
}
