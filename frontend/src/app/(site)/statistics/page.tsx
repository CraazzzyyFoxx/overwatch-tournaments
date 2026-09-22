import React, { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { Map as MapIcon, Percent, Trophy } from "lucide-react";

import { LeaderboardCard } from "@/components/stats/LeaderboardCard";
import { PlatformStatsGrid } from "@/components/stats/PlatformStatsGrid";
import TournamentsChart from "@/components/TournamentsChart";
import TournamentsDivisionChart from "@/components/TournamentsDivisionChart";
import statisticsService from "@/services/statistics.service";
import { isTenantHost } from "@/lib/site/tenant-host";
import type {
  PlayerStatistics,
  TournamentDivisionStatistics,
  TournamentStatistics,
} from "@/types/statistics.types";
import {
  ChartCardSkeleton,
  StatsGridSkeleton,
  TableCardSkeleton,
} from "@/components/skeletons/dashboard-skeletons";

export const dynamic = "force-dynamic";

const LEADERBOARD_SIZE = 15;

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────

export default async function StatisticsPage() {
  const t = await getTranslations();
  return (
    <div className="space-y-8">
      <header>
        <p className="mb-2 text-label font-semibold tracking-label uppercase text-muted-foreground/50">
          {t("statistics.eyebrow")}
        </p>
        <h1 className="font-display text-3xl font-bold uppercase tracking-wide text-foreground">
          {t("statistics.title")}
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          {t("statistics.description")}
        </p>
      </header>

      <section>
        <Suspense fallback={<StatsGridSkeleton />}>
          <OverallStats />
        </Suspense>
      </section>

      <section className="space-y-4">
        <SectionLabel>{t("statistics.trendsOverTime")}</SectionLabel>
        <Suspense fallback={<ChartCardSkeleton />}>
          <ActivityTrendCard />
        </Suspense>
        <Suspense fallback={<ChartCardSkeleton />}>
          <DivisionTrendCard />
        </Suspense>
      </section>

      <section className="space-y-4">
        <SectionLabel>{t("statistics.leaderboards")}</SectionLabel>
        <div className="grid gap-4 lg:grid-cols-3">
          <Suspense fallback={<TableCardSkeleton />}>
            <ChampionsLeaderboard />
          </Suspense>
          <Suspense fallback={<TableCardSkeleton />}>
            <WinRateLeaderboard />
          </Suspense>
          <Suspense fallback={<TableCardSkeleton />}>
            <WonMapsLeaderboard />
          </Suspense>
        </div>
      </section>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Primitives
// ─────────────────────────────────────────────────────────────────────────────

function SectionLabel({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <p className="text-label font-semibold tracking-label uppercase text-muted-foreground/50">
      {children}
    </p>
  );
}

function DashCard({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: "var(--aqt-bg-2)", border: "1px solid var(--aqt-border)" }}
    >
      {children}
    </div>
  );
}

function DashCardHeader({ icon, children }: Readonly<{ icon?: React.ReactNode; children: React.ReactNode }>) {
  return (
    <div
      className="flex items-center gap-2 px-5 py-4 border-b font-display font-bold text-ui uppercase tracking-[0.04em]"
      style={{ borderColor: "var(--aqt-border)", color: "var(--aqt-fg)" }}
    >
      {icon}
      {children}
    </div>
  );
}

function ErrorBody({ message }: Readonly<{ message: string }>) {
  return <div className="px-5 py-4 text-sm text-muted-foreground">{message}</div>;
}


// ─────────────────────────────────────────────────────────────────────────────
// Overall KPI strip
// ─────────────────────────────────────────────────────────────────────────────

async function OverallStats() {
  const t = await getTranslations();
  const skipWorkspace = !(await isTenantHost());
  let overall = null;
  try {
    overall = await statisticsService.getOverallStatistics({ skipWorkspace });
  } catch {
    overall = null;
  }

  if (!overall) {
    return (
      <DashCard>
        <ErrorBody message={t("common.loadError")} />
      </DashCard>
    );
  }

  return <PlatformStatsGrid totals={overall} />;
}

// ─────────────────────────────────────────────────────────────────────────────
// Trend charts (full recharts versions, not on the home summary)
// ─────────────────────────────────────────────────────────────────────────────

async function ActivityTrendCard() {
  const t = await getTranslations();
  const skipWorkspace = !(await isTenantHost());
  let data: TournamentStatistics[] | null = null;
  try {
    data = await statisticsService.getTournaments({ skipWorkspace });
  } catch {
    data = null;
  }

  if (!data || data.length === 0) {
    return (
      <DashCard>
        <DashCardHeader>{t("statistics.tournamentActivity")}</DashCardHeader>
        <ErrorBody message={data ? t("common.noData") : t("common.loadError")} />
      </DashCard>
    );
  }
  return <TournamentsChart data={data} />;
}

async function DivisionTrendCard() {
  const t = await getTranslations();
  const skipWorkspace = !(await isTenantHost());
  let data: TournamentDivisionStatistics[] | null = null;
  try {
    data = await statisticsService.getTournamentsDivision({ skipWorkspace });
  } catch {
    data = null;
  }

  if (!data || data.length === 0) {
    return (
      <DashCard>
        <DashCardHeader>{t("statistics.avgDivisionByRole")}</DashCardHeader>
        <ErrorBody message={data ? t("common.noData") : t("common.loadError")} />
      </DashCard>
    );
  }
  return <TournamentsDivisionChart data={data} />;
}

// ─────────────────────────────────────────────────────────────────────────────
// Leaderboards
// ─────────────────────────────────────────────────────────────────────────────

async function ChampionsLeaderboard() {
  const t = await getTranslations();
  const skipWorkspace = !(await isTenantHost());
  let rows: PlayerStatistics[] = [];
  try {
    rows = (await statisticsService.getChampions({ skipWorkspace })).results.slice(
      0,
      LEADERBOARD_SIZE,
    );
  } catch {
    rows = [];
  }
  return (
    <LeaderboardCard
      title={t("statistics.mostChampionships")}
      icon={<Trophy className="h-4 w-4 text-[color:var(--aqt-amber)]" />}
      rows={rows}
      format={(v) => `${v}×`}
      accent="teal"
    />
  );
}

async function WinRateLeaderboard() {
  const t = await getTranslations();
  const skipWorkspace = !(await isTenantHost());
  let rows: PlayerStatistics[] = [];
  try {
    rows = (await statisticsService.getTopWinratePlayers({ skipWorkspace })).results.slice(
      0,
      LEADERBOARD_SIZE,
    );
  } catch {
    rows = [];
  }
  return (
    <LeaderboardCard
      title={t("statistics.topWinRate")}
      icon={<Percent className="h-4 w-4 text-[color:var(--aqt-emerald)]" />}
      rows={rows}
      format={(v) => `${(v * 100).toFixed(1)}%`}
      accent="emerald"
    />
  );
}

async function WonMapsLeaderboard() {
  const t = await getTranslations();
  const skipWorkspace = !(await isTenantHost());
  let rows: PlayerStatistics[] = [];
  try {
    rows = (await statisticsService.getTopWonMapsPlayers({ skipWorkspace })).results.slice(
      0,
      LEADERBOARD_SIZE,
    );
  } catch {
    rows = [];
  }
  return (
    <LeaderboardCard
      title={t("statistics.mostMapsWon")}
      icon={<MapIcon className="h-4 w-4 text-[color:var(--aqt-blue)]" />}
      rows={rows}
      format={(v) => `${v}`}
      accent="blue"
    />
  );
}
