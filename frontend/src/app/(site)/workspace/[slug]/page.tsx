import { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { BarChart3, Percent, Trophy } from "lucide-react";
// Aliased: `dynamic` is taken by the route segment config below.
import nextDynamic from "next/dynamic";

import { PlatformStatsGrid } from "@/components/stats/PlatformStatsGrid";
import {
  EventCard,
  LiveUpcomingBadge,
  EventsSkeleton,
  type TournamentWithCount,
} from "@/components/site/LiveEventsWidgets";
import { LeaderboardCard } from "@/components/stats/LeaderboardCard";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import statisticsService from "@/services/statistics.service";
import heroService from "@/services/hero.service";
import workspaceService from "@/services/workspace.service";
import tournamentService from "@/services/tournament.service";
import {
  ChartCardSkeleton,
  PopularHeroesCardSkeleton,
  StatsGridSkeleton,
  TableCardSkeleton,
} from "@/components/skeletons/dashboard-skeletons";
import { isTournamentStatusActive } from "@/lib/tournament/status";
import type { Workspace } from "@/types/workspace.types";

export const dynamic = "force-dynamic";

// Every chart on this dashboard is recharts (~100 kB), and none of them is
// above the fold on a phone. Loading all three on demand keeps the library out
// of the page's initial client bundle; each placeholder is the height its chart
// settles at, so nothing reflows when the chunk lands.
const TournamentsChart = nextDynamic(() => import("@/components/TournamentsChart"), {
  loading: () => <Skeleton className="aspect-video w-full" />
});
const TournamentsDivisionChart = nextDynamic(
  () => import("@/components/TournamentsDivisionChart"),
  { loading: () => <Skeleton className="aspect-video w-full" /> }
);
const HeroPlaytimeChart = nextDynamic(() => import("@/components/HeroPlaytimeChart"), {
  loading: () => <Skeleton className="h-100 w-full rounded-lg" />
});

// ─────────────────────────────────────────────────────────────────────────────
// Root page
// ─────────────────────────────────────────────────────────────────────────────

export default async function WorkspaceHome({
  params,
}: Readonly<{
  params: Promise<{ slug: string }>;
}>) {
  const { slug } = await params;
  const t = await getTranslations();

  let workspace: Workspace;
  try {
    // `all`, not the public directory: a workspace's own page must stay
    // reachable for its members while it is still `unverified` or hidden.
    const workspaces = await workspaceService.getAll("all");
    const found = workspaces.find((w) => w.slug === slug);
    if (!found) notFound();
    workspace = found;
  } catch {
    notFound();
  }

  const wsId = workspace.id;

  return (
    <div className="space-y-8">
      {/* Workspace header */}
      <WorkspaceHeader workspace={workspace} />

      {/* Live / upcoming events for this workspace */}
      <section>
        <Suspense fallback={<EventsSkeleton />}>
          <WorkspaceEventsSection workspace={workspace} />
        </Suspense>
      </section>

      {/* Stats */}
      <Suspense fallback={<StatsGridSkeleton />}>
        <StatsGrid workspaceId={wsId} />
      </Suspense>

      {/* Charts + tables */}
      <div className="liquid-glass rounded-xl">
        <div className="flex flex-col gap-1.5 p-6">
          <h2 className="text-3xl font-bold tracking-tight text-foreground font-display uppercase">
            {t("workspace.dashboard")}
          </h2>
          <p className="text-base text-muted-foreground max-w-lg">
            {t.rich("workspace.dashboardLede", {
              name: workspace.name,
              hl: (chunks) => (
                <span className="text-foreground font-medium">{chunks}</span>
              ),
            })}
          </p>
        </div>
      </div>

      <div className="grid gap-6 md:gap-8 lg:grid-cols-2">
        <div className="liquid-glass rounded-xl h-full">
          <Suspense fallback={<ChartCardSkeleton />}>
            <TournamentsChartCard workspaceId={wsId} />
          </Suspense>
        </div>

        <div className="liquid-glass rounded-xl h-full">
          <Suspense fallback={<ChartCardSkeleton />}>
            <TournamentsDivisionChartCard workspaceId={wsId} />
          </Suspense>
        </div>
      </div>

      <div className="grid gap-6 md:gap-8 lg:grid-cols-8 pb-8">
        <div className="liquid-glass rounded-xl h-full lg:col-span-2">
          <Suspense fallback={<TableCardSkeleton />}>
            <ChampionsLeaderboard workspaceId={wsId} />
          </Suspense>
        </div>

        <div className="liquid-glass rounded-xl h-full lg:col-span-2">
          <Suspense fallback={<TableCardSkeleton />}>
            <TopWinrateLeaderboard workspaceId={wsId} />
          </Suspense>
        </div>

        <div className="liquid-glass rounded-xl h-full lg:col-span-4">
          <Suspense fallback={<PopularHeroesCardSkeleton />}>
            <PopularHeroesCard workspaceId={wsId} />
          </Suspense>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Workspace header
// ─────────────────────────────────────────────────────────────────────────────

async function WorkspaceHeader({ workspace }: Readonly<{ workspace: Workspace }>) {
  const t = await getTranslations();
  return (
    <div className="liquid-glass rounded-xl p-6 flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
      <div className="flex flex-col gap-1.5">
        <p className="text-xs font-semibold uppercase tracking-label text-muted-foreground">
          {t("workspace.eyebrow")}
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-foreground font-display uppercase">
          {workspace.name}
        </h1>
        {workspace.description && (
          <p className="text-base text-muted-foreground max-w-lg">
            {workspace.description}
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button asChild size="lg" className="shadow-lg shadow-primary/20">
          <Link href={`/tournaments`}>
            <Trophy className="mr-2 h-5 w-5" />
            {t("common.tournaments")}
          </Link>
        </Button>
        <Button asChild variant="secondary" size="lg">
          <Link href="/tournaments/analytics">
            <BarChart3 className="mr-2 h-5 w-5" />
            {t("common.analytics")}
          </Link>
        </Button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Active events for this workspace
// ─────────────────────────────────────────────────────────────────────────────

async function WorkspaceEventsSection({ workspace }: Readonly<{ workspace: Workspace }>) {
  let activeTournaments: TournamentWithCount[] = [];

  try {
    const data = await tournamentService.getActive();
    activeTournaments = (data.results as TournamentWithCount[])
      .filter((tour) => tour.workspace_id === workspace.id && isTournamentStatusActive(tour.status))
      .slice(0, 6);
  } catch {
    // silently fail
  }

  if (activeTournaments.length === 0) return null;

  const liveCount = activeTournaments.filter(
    (tour) => tour.status === "live" || tour.status === "playoffs"
  ).length;
  const upcomingCount = activeTournaments.length - liveCount;

  return (
    <div>
      <LiveUpcomingBadge
        liveCount={liveCount}
        upcomingCount={upcomingCount}
        dotClassName="bg-emerald-400"
        textClassName="text-emerald-400"
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {activeTournaments.map((tour) => (
          <EventCard key={tour.id} tournament={tour} workspace={workspace} />
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Stats grid
// ─────────────────────────────────────────────────────────────────────────────

async function StatsGrid({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const t = await getTranslations();
  let overall = null;
  let hasError = false;
  try {
    overall = await statisticsService.getOverallStatistics({ workspaceId });
  } catch {
    hasError = true;
  }

  if (hasError || !overall) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="md:col-span-2 lg:col-span-4 border-destructive/50">
          <CardHeader><CardTitle>{t("statistics.overallStatistics")}</CardTitle></CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {t("common.loadError")}
          </CardContent>
        </Card>
      </div>
    );
  }

  return <PlatformStatsGrid totals={overall} />;
}

// ─────────────────────────────────────────────────────────────────────────────
// Dashboard cards
// ─────────────────────────────────────────────────────────────────────────────

async function TournamentsChartCard({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const t = await getTranslations();
  let tournaments = null;
  let hasError = false;
  try {
    tournaments = await statisticsService.getTournaments({ workspaceId });
  } catch {
    hasError = true;
  }

  if (hasError || !tournaments) {
    return (
      <Card className="border-0 shadow-none bg-card/80 backdrop-blur-sm h-full">
        <CardHeader><CardTitle>{t("workspace.tournamentHistory")}</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {t("common.loadError")}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="bg-card/80 backdrop-blur-sm h-full rounded-xl w-full">
      <TournamentsChart data={tournaments} />
    </div>
  );
}

async function TournamentsDivisionChartCard({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const t = await getTranslations();
  let data = null;
  let hasError = false;
  try {
    data = await statisticsService.getTournamentsDivision({ workspaceId });
  } catch {
    hasError = true;
  }

  if (hasError || !data) {
    return (
      <Card className="border-0 shadow-none bg-card/80 backdrop-blur-sm h-full">
        <CardHeader><CardTitle>{t("workspace.avgDivisionByRoles")}</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {t("common.loadError")}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="bg-card/80 backdrop-blur-sm h-full rounded-xl w-full">
      <TournamentsDivisionChart data={data} />
    </div>
  );
}

async function ChampionsLeaderboard({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const t = await getTranslations();
  let champions = null;
  let hasError = false;
  try {
    champions = await statisticsService.getChampions({ workspaceId });
  } catch {
    hasError = true;
  }

  if (hasError || !champions) {
    return (
      <Card className="border-0 shadow-none bg-card/80 backdrop-blur-sm h-full">
        <CardHeader><CardTitle>{t("common.champions")}</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">{t("common.loadError")}</CardContent>
      </Card>
    );
  }

  return (
    <div className="bg-card/80 backdrop-blur-sm rounded-xl h-full border-0">
      <LeaderboardCard
        title={t("common.champions")}
        icon={<Trophy className="h-4 w-4 text-[color:var(--aqt-amber)]" />}
        rows={champions.results}
        format={(value) => `${value}×`}
        accent="teal"
      />
    </div>
  );
}

async function TopWinrateLeaderboard({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const t = await getTranslations();
  let players = null;
  let hasError = false;
  try {
    players = await statisticsService.getTopWinratePlayers({ workspaceId });
  } catch {
    hasError = true;
  }

  if (hasError || !players) {
    return (
      <Card className="border-0 shadow-none bg-card/80 backdrop-blur-sm h-full">
        <CardHeader><CardTitle>{t("workspace.topPlayersByWinRatio")}</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {t("common.loadError")}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="bg-card/80 backdrop-blur-sm rounded-xl h-full border-0">
      <LeaderboardCard
        title={t("workspace.topPlayersByWinRatio")}
        icon={<Percent className="h-4 w-4 text-[color:var(--aqt-emerald)]" />}
        rows={players.results}
        format={(value) => (Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "-")}
        accent="emerald"
      />
    </div>
  );
}

async function PopularHeroesCard({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const t = await getTranslations();
  let heroPlaytime = null;
  let hasError = false;
  try {
    heroPlaytime = await heroService.getHeroPlaytime(1, 10, "all", null, { workspaceId });
  } catch {
    hasError = true;
  }

  if (hasError || !heroPlaytime) {
    return (
      <Card className="border-0 shadow-none bg-card/80 backdrop-blur-sm h-full">
        <CardHeader><CardTitle>{t("workspace.popularHeroes")}</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {t("common.loadError")}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-0 shadow-none bg-card/80 backdrop-blur-sm h-full">
      <CardHeader><CardTitle>{t("workspace.popularHeroes")}</CardTitle></CardHeader>
      <CardContent className="p-0 pb-2">
        <HeroPlaytimeChart heroes={heroPlaytime.results} />
      </CardContent>
    </Card>
  );
}
