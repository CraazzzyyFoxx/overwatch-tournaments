"use client";

import { useTranslations } from "next-intl";

import { StatusPill } from "@/components/kit/StatusPill";
import { TONE_TEXT } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { reportOf, scoreline } from "@/lib/encounter/reports";
import { seatsBySlot } from "@/lib/encounter/seats";
import { cn } from "@/lib/utils";
import type { AdminCaptainReport, EncounterParticipationRef } from "@/types/admin.types";

interface AdminReportPairCellProps {
  /** The encounter's live seats; their slot order is the order everything below reads in. */
  participations: EncounterParticipationRef[];
  reports: AdminCaptainReport[];
  /** `null` = not every participation has reported, so agreement is not yet knowable. */
  standingsMatch: boolean | null;
  /**
   * Pass only where the cell is the whole picture (the resolve dialog): false
   * adds the advisory that a reported standing cannot happen in this best-of.
   * The reports table leaves it out; its inspector says it once.
   */
  seriesScoreValid?: boolean;
  className?: string;
}

function ReportSeat({
  label,
  report,
  standing,
  t
}: Readonly<{
  label: string;
  report: AdminCaptainReport | null;
  standing: string;
  t: (key: "unknown" | "noReport" | "scoreOutside") => string;
}>) {
  return (
    <div className="min-w-0">
      <p className="truncate text-caption font-medium text-muted-foreground">{label}</p>
      {report ? (
        <>
          <p className="text-sm font-semibold tabular-nums">{standing}</p>
          <p className="truncate text-xs text-muted-foreground">
            {report.reporter_name ?? t("unknown")}
            {/* Match quality is configurable per tournament, so an absent rating
                is a legitimate report: it is left out, not printed as NaN. */}
            {report.closeness == null ? null : <> &middot; <span className="tabular-nums">{report.closeness}/10</span></>}
          </p>
          {report.comment ? (
            // Clamped rather than hidden: an organizer settling a dispute needs
            // to read what the captain wrote, and `title` carries the rest.
            <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground" title={report.comment}>
              &ldquo;{report.comment}&rdquo;
            </p>
          ) : null}
        </>
      ) : (
        <p className="text-xs text-muted-foreground">{t("noReport")}</p>
      )}
    </div>
  );
}

/**
 * Every participation's report for one encounter, side by side in slot order.
 *
 * Agreement is three-valued, but only one value wants an admin: two reports
 * that disagree. That is the one pill; agreement and a report still awaited
 * are the absence of it, since the reports themselves sit right above.
 */
export function AdminReportPairCell({
  participations,
  reports,
  standingsMatch,
  seriesScoreValid,
  className
}: Readonly<AdminReportPairCellProps>) {
  const t = useTranslations("adminMatches.common");
  const reportsT = useTranslations("adminMatches.reports");
  const seats = seatsBySlot(participations);
  const seatIds = seats.map((seat) => seat.encounter_team_id);

  return (
    <div className={cn("space-y-2", className)}>
      <div className="grid grid-cols-2 gap-3">
        {seats.map((seat) => {
          const report = reportOf(reports, seat.encounter_team_id);
          return (
            <ReportSeat
              key={seat.encounter_team_id}
              label={seat.name}
              report={report}
              standing={report ? scoreline(report.results, seatIds) : ""}
              t={t}
            />
          );
        })}
      </div>
      {standingsMatch === false ? <StatusPill tone="danger">{reportsT("reportsDisagree")}</StatusPill> : null}
      {seriesScoreValid === false ? (
        // Advisory, not an error: reports predate per-round best-of.
        <p className={cn("text-xs", TONE_TEXT.warning)} title={reportsT("outsideBoTitle")}>
          {t("scoreOutside")}
        </p>
      ) : null}
    </div>
  );
}
