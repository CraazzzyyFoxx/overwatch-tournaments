"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";
import captainService from "@/services/captain.service";
import type {
  CaptainReport,
  Encounter,
  EncounterTeam,
  MatchReportForm,
  ReplayCode
} from "@/types/encounter.types";
import { duelSeats, type DuelSlot } from "@/lib/encounter/seats";
import { TournamentTeamCardFrame } from "@/components/TournamentTeamCard";
import { Alert } from "@/components/ui/alert";
import { Eyebrow } from "@/components/ui/eyebrow";
import { CARD_SUB, SIDE_TEXT, SectionHead } from "@/components/match/EncounterAtoms";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

const REPORT_FIELD = "flex min-w-0 flex-col gap-1";
const REPORT_VALUE =
  "whitespace-pre-wrap text-caption leading-normal wrap-anywhere text-[color:var(--aqt-fg-muted)]";

interface EncounterCaptainReportsProps {
  encounterId: number;
  teams: Encounter["teams"];
}

/** The score a report gave one seat; null when the report has no line for it. */
function reportedScore(report: CaptainReport, seat: EncounterTeam | null): number | null {
  return report.results.find((line) => line.encounter_team_id === seat?.id)?.score ?? null;
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
  teams
}: Readonly<EncounterCaptainReportsProps>) {
  const t = useTranslations();
  const reportsQuery = useQuery({
    queryKey: encounterQueryKeys.reports(encounterId),
    queryFn: () => captainService.getReports(encounterId),
    retry: false,
    staleTime: 60_000
  });

  const reports = reportsQuery.data?.reports ?? [];
  if (reports.length === 0) return null;

  const [seatOne, seatTwo] = duelSeats(teams);
  const disagree =
    reports.length > 1 &&
    reports.some(
      (report) =>
        reportedScore(report, seatOne) !== reportedScore(reports[0], seatOne) ||
        reportedScore(report, seatTwo) !== reportedScore(reports[0], seatTwo)
    );

  const seatOf = (report: CaptainReport): EncounterTeam | null =>
    teams.find((seat) => seat.id === report.encounter_team_id) ?? null;
  const seatNameOf = (report: CaptainReport): string => seatOf(report)?.name ?? t("common.unknown");

  return (
    // Own the section: an encounter whose captains never filed anything renders
    // nothing at all, and a heading over emptiness is worse than no heading.
    <section aria-label={t("encounters.detail.reports")}>
      <SectionHead
        title={t("encounters.detail.reports")}
        meta={t("encounters.detail.reportsMeta", { count: reports.length })}
      />
      <div className="flex flex-col gap-3.5">
        {disagree ? (
          <Alert tone="warning">
            <TriangleAlert aria-hidden />
            <p>{t("encounters.detail.reportsDisagree")}</p>
          </Alert>
        ) : null}
        <div className="grid grid-cols-1 items-start gap-3.5 xl:grid-cols-2">
          {reports.map((report) => (
            <ReportCard
              key={report.id}
              report={report}
              teamName={seatNameOf(report)}
              slot={seatOf(report)?.slot === 2 ? 2 : 1}
              seatOne={seatOne}
              seatTwo={seatTwo}
              form={reportsQuery.data?.form}
              replayCodes={(reportsQuery.data?.replay_codes ?? []).filter(
                (code) => code.encounter_team_id === report.encounter_team_id
              )}
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
  slot,
  seatOne,
  seatTwo,
  form,
  replayCodes
}: Readonly<{
  report: CaptainReport;
  teamName: string;
  slot: DuelSlot;
  seatOne: EncounterTeam | null;
  seatTwo: EncounterTeam | null;
  form?: MatchReportForm;
  /** This participation's codes by position (`game_team.replay_code`). */
  replayCodes: ReplayCode[];
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const submittedAt = report.updated_at ?? report.created_at;
  const customFields = form?.custom_fields ?? [];
  const filed = [
    report.reporter_name,
    submittedAt
      ? format.dateTime(new Date(submittedAt), {
          day: "numeric",
          month: "short",
          hour: "2-digit",
          minute: "2-digit"
        })
      : null
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    // The seat's card: its hue along the top edge, the same frame as the rosters.
    <TournamentTeamCardFrame
      slot={slot}
      name={teamName}
      metricValue={filed ? <span className={cn(CARD_SUB, "font-normal")}>{filed}</span> : undefined}
    >
      <div className="flex flex-col gap-3 p-3.5">
        <div className={REPORT_FIELD}>
          <Eyebrow>{t("encounters.detail.reportedScore")}</Eyebrow>
          <span className="flex items-baseline gap-2 font-display text-title font-bold tabular-nums">
            <span className={SIDE_TEXT[1]}>{reportedScore(report, seatOne)}</span>
            <span aria-hidden className="text-body text-[color:var(--aqt-fg-faint)]">
              :
            </span>
            <span className={SIDE_TEXT[2]}>{reportedScore(report, seatTwo)}</span>
          </span>
        </div>

        {report.closeness != null ? (
          <div className={REPORT_FIELD}>
            <Eyebrow>{t("encounters.detail.reportedCloseness")}</Eyebrow>
            <span className={cn(REPORT_VALUE, "aqt-tnum")}>
              {t("encounters.detail.reportedClosenessValue", { value: report.closeness })}
            </span>
          </div>
        ) : null}

        {replayCodes.length > 0 ? (
          <div className={REPORT_FIELD}>
            <Eyebrow>{t("encounters.detail.reportedCodes")}</Eyebrow>
            <span className="flex flex-wrap gap-x-4 gap-y-1">
              {[...replayCodes]
                .sort((a, b) => a.position - b.position)
                .map(({ position, code }) => (
                  <span
                    key={position}
                    className={cn(CARD_SUB, "tracking-[0.06em] text-[color:var(--aqt-fg-muted)]")}
                  >
                    {t("common.matchLogs.map", { index: position })} · {code}
                  </span>
                ))}
            </span>
          </div>
        ) : null}

        {report.comment ? (
          <div className={REPORT_FIELD}>
            <Eyebrow>{t("encounters.detail.reportedComment")}</Eyebrow>
            <p className={REPORT_VALUE}>{report.comment}</p>
          </div>
        ) : null}

        {customFields.map((definition) => {
          const value = report.custom_fields?.[definition.key];
          if (!value) return null;
          return (
            <div key={definition.key} className={REPORT_FIELD}>
              <Eyebrow>{definition.label}</Eyebrow>
              <p className={REPORT_VALUE}>{value}</p>
            </div>
          );
        })}
      </div>
    </TournamentTeamCardFrame>
  );
}

export type { EncounterCaptainReportsProps };
