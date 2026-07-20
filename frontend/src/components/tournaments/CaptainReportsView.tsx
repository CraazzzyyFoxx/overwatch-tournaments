"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { CaptainReport, Encounter } from "@/types/encounter.types";

interface CaptainReportsViewProps {
  encounter: Encounter;
  reports: CaptainReport[];
  className?: string;
}

function pickReport(
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
}: {
  title: string;
  teamName: string;
  report: CaptainReport | null;
}) {
  const t = useTranslations();

  return (
    <div className="rounded-xl border border-zinc-800/80 bg-zinc-950/40 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-500">{title}</p>
        <p className="truncate text-xs font-semibold text-zinc-300">{teamName}</p>
      </div>
      {report ? (
        <div className="mt-2 space-y-1.5 text-sm text-zinc-200">
          <div className="font-mono text-base font-bold text-white">
            {report.home_score} - {report.away_score}
          </div>
          <div className="text-xs text-zinc-400">
            {t("matchReport.matchQuality")}: {report.closeness}/10
          </div>
          {report.map_codes.length > 0 && (
            <ul className="mt-1 space-y-0.5">
              {report.map_codes
                .slice()
                .sort((a, b) => a.map_index - b.map_index)
                .map((mapCode) => (
                  <li key={mapCode.id} className="flex items-center gap-2 text-xs text-zinc-400">
                    <span className="text-zinc-500">
                      {t("matchReport.mapLabel", { index: String(mapCode.map_index) })}
                    </span>
                    <span className="font-mono text-zinc-200">{mapCode.code}</span>
                  </li>
                ))}
            </ul>
          )}
        </div>
      ) : (
        <p className="mt-2 text-xs italic text-zinc-500">{t("matchReport.noReportYet")}</p>
      )}
    </div>
  );
}

export function CaptainReportsView({ encounter, reports, className }: CaptainReportsViewProps) {
  const t = useTranslations();
  const homeReport = pickReport(reports, "home", encounter.home_team_id);
  const awayReport = pickReport(reports, "away", encounter.away_team_id);
  const homeLabel = encounter.home_team?.name?.trim() || t("common.homeTeam");
  const awayLabel = encounter.away_team?.name?.trim() || t("common.awayTeam");
  const avgCloseness =
    homeReport && awayReport ? (homeReport.closeness + awayReport.closeness) / 2 : null;

  return (
    <div className={cn("space-y-2", className)}>
      <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-500">
        {t("matchReport.bothReportsTitle")}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <ReportCard title={t("matchReport.homeReport")} teamName={homeLabel} report={homeReport} />
        <ReportCard title={t("matchReport.awayReport")} teamName={awayLabel} report={awayReport} />
      </div>
      {avgCloseness != null && (
        <p className="text-xs text-zinc-400">
          {t("matchReport.avgCloseness")}: {avgCloseness.toFixed(1)}/10
        </p>
      )}
    </div>
  );
}
