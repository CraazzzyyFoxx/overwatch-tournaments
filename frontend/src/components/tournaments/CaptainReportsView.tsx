"use client";

import { useTranslations } from "next-intl";

import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { cn } from "@/lib/utils";
import { reportOf, scoreline } from "@/lib/encounter/reports";
import { seatsBySlot } from "@/lib/encounter/seats";
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

/** The replay codes a participation entered, by position: they live on the game's lines. */
function replayCodesOf(encounter: Encounter, encounterTeamId: number) {
  return encounter.games
    .flatMap((game) =>
      game.teams
        .filter((line) => line.encounter_team_id === encounterTeamId && line.replay_code)
        .map((line) => ({ position: game.position, code: line.replay_code as string }))
    )
    .sort((a, b) => a.position - b.position);
}

function ReportCard({
  title,
  teamName,
  standing,
  replayCodes,
  report,
  customFields,
}: Readonly<{
  title: string;
  teamName: string;
  standing: string;
  replayCodes: { position: number; code: string }[];
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
        <Eyebrow as="p" tone="dim">{title}</Eyebrow>
        <p className="truncate text-xs font-semibold text-[color:var(--aqt-fg-muted)]">{teamName}</p>
      </div>
      {report ? (
        <div className="mt-2 space-y-1.5 text-sm text-[color:var(--aqt-fg-muted)]">
          <div className="text-base font-bold text-[color:var(--aqt-fg)]">{standing}</div>
          <div className="text-xs text-[color:var(--aqt-fg-muted)]">
            {t("matchReport.matchQuality")}:{" "}
            {report.closeness != null ? `${report.closeness}/10` : "—"}
          </div>
          {replayCodes.length > 0 && (
            <ul className="mt-1 space-y-0.5">
              {replayCodes.map(({ position, code }) => (
                <li key={position} className="flex items-center gap-2 text-xs text-[color:var(--aqt-fg-muted)]">
                  <span className="text-[color:var(--aqt-fg-dim)]">
                    {t("matchReport.mapLabel", { index: String(position) })}
                  </span>
                  <span className="text-[color:var(--aqt-fg-muted)]">{code}</span>
                </li>
              ))}
            </ul>
          )}
          {comment ? (
            <div className="mt-1">
              <Eyebrow as="p" tone="dim">
                {t("matchReport.comment")}
              </Eyebrow>
              <p className="mt-0.5 whitespace-pre-wrap break-words text-xs text-[color:var(--aqt-fg-muted)]">
                {comment}
              </p>
            </div>
          ) : null}
          {customAnswers.length > 0 && (
            <dl className="mt-1 space-y-1">
              {customAnswers.map(([key, value]) => (
                <div key={key}>
                  <Eyebrow as="dt" tone="dim">
                    {customFields.find((field) => field.key === key)?.label ?? key}
                  </Eyebrow>
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
  const seats = seatsBySlot(encounter.teams);
  const seatIds = seats.map((seat) => seat.id);
  const seatReports = seats.map((seat) => reportOf(reports, seat.id));
  const customFields = form?.custom_fields ?? [];
  // Averaging needs every seat's rating; one unrated seat makes the average a
  // lie, not a smaller number.
  const ratings = seatReports.map((report) => report?.closeness);
  const avgCloseness =
    seats.length > 0 && ratings.every((rating) => rating != null)
      ? (ratings as number[]).reduce((sum, rating) => sum + rating, 0) / ratings.length
      : null;

  return (
    <div className={cn("space-y-2", className)}>
      <Eyebrow as="p" tone="dim">
        {t("matchReport.bothReportsTitle")}
      </Eyebrow>
      <div className="grid gap-3 sm:grid-cols-2">
        {seats.map((seat, index) => {
          const report = seatReports[index];
          return (
            <ReportCard
              key={seat.id}
              title={t("matchReport.teamReport")}
              teamName={seat.name}
              standing={report ? scoreline(report.results, seatIds) : ""}
              replayCodes={replayCodesOf(encounter, seat.id)}
              report={report}
              customFields={customFields}
            />
          );
        })}
      </div>
      {avgCloseness != null && (
        <p className="text-xs text-[color:var(--aqt-fg-muted)]">
          {t("matchReport.avgCloseness")}: {avgCloseness.toFixed(1)}/10
        </p>
      )}
    </div>
  );
}
