"use client";

import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";
import captainService from "@/services/captain.service";
import type { CaptainReport, MatchReportForm } from "@/types/encounter.types";
import { Pill, PillFact } from "@/components/match/EncounterAtoms";
import styles from "@/components/match/EncounterDetail.module.css";

interface EncounterCaptainReportsProps {
  encounterId: number;
  homeTeamId: number | null;
  awayTeamId: number | null;
  homeName: string;
  awayName: string;
}

/**
 * What the captains actually filed.
 *
 * This is a public (`AuthOptional`) endpoint the detail page never called, so
 * the provenance of a series score — who reported it, what quality they rated
 * the match, which lobby codes were used, and any organizer-defined answers —
 * was invisible outside the admin tools. Renders nothing when no report exists.
 */
export default function EncounterCaptainReports({
  encounterId,
  homeTeamId,
  awayTeamId,
  homeName,
  awayName
}: Readonly<EncounterCaptainReportsProps>) {
  const t = useTranslations();
  const reportsQuery = useQuery({
    queryKey: ["encounter-reports", encounterId],
    queryFn: () => captainService.getReports(encounterId),
    retry: false,
    staleTime: 60_000
  });

  const reports = reportsQuery.data?.reports ?? [];
  if (reports.length === 0) return null;

  const disagree =
    reports.length > 1 &&
    reports.some(
      (report) =>
        report.home_score !== reports[0].home_score || report.away_score !== reports[0].away_score
    );

  const sideName = (report: CaptainReport): string => {
    if (report.side === "home") return homeName;
    if (report.side === "away") return awayName;
    if (report.team_id === homeTeamId) return homeName;
    if (report.team_id === awayTeamId) return awayName;
    return t("common.unknown");
  };

  return (
    // Own the section: an encounter whose captains never filed anything renders
    // nothing at all, and a heading over emptiness is worse than no heading.
    <section aria-label={t("encounters.detail.reports")}>
      <div className={styles.sectionHead}>
        <h2 className={styles.sectionTitle}>{t("encounters.detail.reports")}</h2>
        <span className={styles.sectionMeta}>
          {t("encounters.detail.reportsMeta", { count: reports.length })}
        </span>
      </div>
      <div className={styles.statsStack}>
        {disagree ? (
          <output className={styles.reportMismatch}>
            <TriangleAlert aria-hidden width={15} height={15} className="mt-px shrink-0" />
            {t("encounters.detail.reportsDisagree")}
          </output>
        ) : null}
        <div className={styles.reportGrid}>
          {reports.map((report) => (
            <ReportCard
              key={report.id}
              report={report}
              teamName={sideName(report)}
              side={report.side ?? (report.team_id === awayTeamId ? "away" : "home")}
              form={reportsQuery.data?.form}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

function ReportCard({
  report,
  teamName,
  side,
  form
}: Readonly<{
  report: CaptainReport;
  teamName: string;
  side: "home" | "away";
  form?: MatchReportForm;
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const submittedAt = report.updated_at ?? report.created_at;
  const customFields = form?.custom_fields ?? [];

  return (
    <div className={cn(styles.card, side === "home" ? styles.sideHome : styles.sideAway)}>
      <div className={styles.rosterHead}>
        <h3 className={styles.rosterName}>{teamName}</h3>
        <div className={styles.rosterFacts}>
          {report.reporter_name ? (
            <PillFact label={t("encounters.detail.reportBy")} value={report.reporter_name} />
          ) : null}
          {submittedAt ? (
            <Pill>
              <span className={styles.mono}>
                {format.dateTime(new Date(submittedAt), {
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit"
                })}
              </span>
            </Pill>
          ) : null}
        </div>
      </div>

      <div className={cn(styles.cardBody, styles.reportFields)}>
        <div className={styles.reportField}>
          <span className={styles.label}>{t("encounters.detail.reportedScore")}</span>
          <span className={styles.reportScore}>
            <span className={styles.scoreHome}>{report.home_score}</span>
            <span aria-hidden className={styles.scoreSep}>
              :
            </span>
            <span className={styles.scoreAway}>{report.away_score}</span>
          </span>
        </div>

        {report.closeness != null ? (
          <div className={styles.reportField}>
            <span className={styles.label}>{t("encounters.detail.reportedCloseness")}</span>
            <span className={cn(styles.reportValue, styles.mono)}>
              {t("encounters.detail.reportedClosenessValue", { value: report.closeness })}
            </span>
          </div>
        ) : null}

        {report.map_codes.length > 0 ? (
          <div className={styles.reportField}>
            <span className={styles.label}>{t("encounters.detail.reportedCodes")}</span>
            <span className={styles.reportCodes}>
              {[...report.map_codes]
                .sort((a, b) => a.map_index - b.map_index)
                .map((entry) => (
                  <span key={entry.id} className={styles.reportCode}>
                    {t("common.matchLogs.map", { index: entry.map_index + 1 })} · {entry.code}
                  </span>
                ))}
            </span>
          </div>
        ) : null}

        {report.comment ? (
          <div className={styles.reportField}>
            <span className={styles.label}>{t("encounters.detail.reportedComment")}</span>
            <p className={styles.reportValue}>{report.comment}</p>
          </div>
        ) : null}

        {customFields.map((definition) => {
          const value = report.custom_fields?.[definition.key];
          if (!value) return null;
          return (
            <div key={definition.key} className={styles.reportField}>
              <span className={styles.label}>{definition.label}</span>
              <p className={styles.reportValue}>{value}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export type { EncounterCaptainReportsProps };
