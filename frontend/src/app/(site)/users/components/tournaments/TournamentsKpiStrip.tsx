"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { UserProfile, UserTournament } from "@/types/user.types";
import { leagueKey } from "@/app/(site)/users/components/tournaments/tournaments-history.helpers";

interface Props {
  /** Career totals (Played / Titles / Avg placement). Falls back to list-derived
   *  values when absent so the strip is never blank. */
  profile: UserProfile | null;
  tournaments: UserTournament[];
}

const KpiCard = ({
  label,
  value,
  sub,
  color
}: {
  label: string;
  value: string;
  sub?: string | null;
  color?: string;
}) => (
  <div className="flex flex-col gap-1 rounded-[10px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-4 py-3">
    <span className="aqt-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
      {label}
    </span>
    <span className="aqt-display aqt-tnum text-[30px] font-bold leading-none" style={{ color: color ?? "var(--aqt-fg)" }}>
      {value}
    </span>
    {sub ? (
      <span className="aqt-mono text-[11px] text-[color:var(--aqt-fg-dim)]">{sub}</span>
    ) : (
      <span aria-hidden="true" className="aqt-mono select-none text-[11px] text-transparent">
        ·
      </span>
    )}
  </div>
);

const TournamentsKpiStrip = ({ profile, tournaments }: Props) => {
  const t = useTranslations();

  const placed = tournaments.filter((tour) => tour.placement && tour.count_teams);
  const podiumCount = placed.filter((tour) => tour.placement <= 3).length;
  const podiumRate = placed.length > 0 ? Math.round((podiumCount / placed.length) * 100) : null;
  const bestPlacement = placed.length > 0 ? Math.min(...placed.map((tour) => tour.placement)) : null;
  const leagueCount = new Set(tournaments.filter((tour) => tour.is_league).map(leagueKey)).size;

  const listTitles = tournaments.filter((tour) => tour.placement === 1).length;
  const listAvg = placed.length > 0 ? placed.reduce((sum, tour) => sum + tour.placement, 0) / placed.length : null;

  const played = profile?.tournaments_count ?? tournaments.length;
  const titles = profile?.tournaments_won ?? listTitles;
  const avgPlacement = profile?.avg_placement ?? listAvg;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <KpiCard
        label={t("users.tournaments.kpi.played")}
        value={String(played)}
        sub={leagueCount > 0 ? t("users.tournaments.kpi.leaguesSub", { count: String(leagueCount) }) : null}
      />
      <KpiCard
        label={t("users.tournaments.kpi.titles")}
        value={String(titles)}
        color={titles > 0 ? "var(--aqt-amber)" : undefined}
        sub={podiumCount > 0 ? t("users.tournaments.kpi.podiumsSub", { count: String(podiumCount) }) : null}
      />
      <KpiCard
        label={t("users.tournaments.kpi.podiumRate")}
        value={podiumRate != null ? `${podiumRate}%` : "—"}
        sub={placed.length > 0 ? t("users.tournaments.kpi.ofEvents", { podium: String(podiumCount), total: String(placed.length) }) : null}
      />
      <KpiCard
        label={t("users.tournaments.kpi.avgPlacement")}
        value={avgPlacement != null && Number.isFinite(avgPlacement) ? avgPlacement.toFixed(1) : "—"}
        sub={bestPlacement != null ? t("users.tournaments.kpi.bestSub", { n: String(bestPlacement) }) : null}
      />
    </div>
  );
};

export default TournamentsKpiStrip;
