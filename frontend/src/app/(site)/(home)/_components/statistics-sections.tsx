import { getTranslations } from "next-intl/server";

import statisticsService from "@/services/statistics.service";
import { PlatformStatsGrid } from "@/components/stats/PlatformStatsGrid";
import { PageStateCard } from "@/components/ui/page-state-card";
import type { PlayerStatistics } from "@/types/statistics.types";

import { getTenantMode } from "./home.helpers";
import { TopListCard } from "./dashboard-card-shell";

/** Platform-wide totals strip — players, tournaments, games, parsed logs. */
export async function StatsGridSection() {
  const skipWorkspace = !(await getTenantMode());
  let overall = null;
  try {
    overall = await statisticsService.getOverallStatistics({ skipWorkspace });
  } catch {
    // Fail silently
  }

  if (!overall) {
    return <PageStateCard state="error" />;
  }

  return <PlatformStatsGrid totals={overall} />;
}

export async function ChampionsCard() {
  const t = await getTranslations();
  const skipWorkspace = !(await getTenantMode());
  let top: PlayerStatistics[] | null = null;
  try {
    const data = await statisticsService.getChampions({ skipWorkspace });
    top = data.results.slice(0, 5);
  } catch {
    // Fail silently
  }

  return (
    <TopListCard
      title={t("statistics.mostChampionships")}
      top={top}
      valueFormatter={(value) => `${value}×`}
      accent="var(--aqt-teal)"
    />
  );
}

export async function TopWinRateCard() {
  const t = await getTranslations();
  const skipWorkspace = !(await getTenantMode());
  let top: PlayerStatistics[] | null = null;
  try {
    const data = await statisticsService.getTopWinratePlayers({ skipWorkspace });
    top = data.results.slice(0, 5);
  } catch {
    // Fail silently
  }

  return (
    <TopListCard
      title={t("statistics.topWinRate")}
      top={top}
      valueFormatter={(value) => `${(value * 100).toFixed(1)}%`}
      accent="var(--aqt-emerald)"
    />
  );
}
