import React, { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { Award, BarChart3, Scale, Trophy, Users } from "lucide-react";

import StatisticsCard from "@/components/StatisticsCard";
import TournamentsChart from "@/components/TournamentsChart";
import TournamentsDivisionChart from "@/components/TournamentsDivisionChart";
import ChampionsTable from "@/components/ChampionsTable";
import TopWinratePlayersTable from "@/components/TopWinratePlayersTable";
import HeroPlaytimeChart from "@/components/HeroPlaytimeChart";
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
} from "@/app/home-skeletons";
import {
  isTournamentStatusActive,
  getTournamentStatusMeta,
} from "@/lib/tournament-status";
import type { Tournament } from "@/types/tournament.types";
import type { Workspace } from "@/types/workspace.types";
import { Calendar, Users as UsersIcon } from "lucide-react";

export const dynamic = "force-dynamic";

// ─────────────────────────────────────────────────────────────────────────────
// Root page
// ─────────────────────────────────────────────────────────────────────────────

export default async function WorkspaceHome({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const t = await getTranslations();

  let workspace: Workspace;
  try {
    const workspaces = await workspaceService.getAll();
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
          <WorkspaceEventsSection workspaceId={wsId} />
        </Suspense>
      </section>

      {/* Stats */}
      <Suspense fallback={<StatsGridSkeleton />}>
        <StatsGrid workspaceId={wsId} />
      </Suspense>

      {/* Charts + tables */}
      <div
        className="liquid-glass rounded-xl"
        style={
          {
            "--lg-a": "30 41 59",
            "--lg-b": "15 23 42",
            "--lg-c": "99 102 241",
          } as React.CSSProperties
        }
      >
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
        <div
          className="liquid-glass rounded-xl h-full"
          style={
            {
              "--lg-a": "15 23 42",
              "--lg-b": "30 41 59",
              "--lg-c": "59 130 246",
            } as React.CSSProperties
          }
        >
          <Suspense fallback={<ChartCardSkeleton />}>
            <TournamentsChartCard workspaceId={wsId} />
          </Suspense>
        </div>

        <div
          className="liquid-glass rounded-xl h-full"
          style={
            {
              "--lg-a": "15 23 42",
              "--lg-b": "30 41 59",
              "--lg-c": "139 92 246",
            } as React.CSSProperties
          }
        >
          <Suspense fallback={<ChartCardSkeleton />}>
            <TournamentsDivisionChartCard workspaceId={wsId} />
          </Suspense>
        </div>
      </div>

      <div className="grid gap-6 md:gap-8 lg:grid-cols-8 pb-8">
        <div
          className="liquid-glass rounded-xl h-full lg:col-span-2"
          style={
            {
              "--lg-a": "15 23 42",
              "--lg-b": "30 41 59",
              "--lg-c": "16 185 129",
            } as React.CSSProperties
          }
        >
          <Suspense fallback={<TableCardSkeleton />}>
            <ChampionsTableCard workspaceId={wsId} />
          </Suspense>
        </div>

        <div
          className="liquid-glass rounded-xl h-full lg:col-span-2"
          style={
            {
              "--lg-a": "15 23 42",
              "--lg-b": "30 41 59",
              "--lg-c": "245 158 11",
            } as React.CSSProperties
          }
        >
          <Suspense fallback={<TableCardSkeleton />}>
            <TopWinratePlayersTableCard workspaceId={wsId} />
          </Suspense>
        </div>

        <div
          className="liquid-glass rounded-xl h-full lg:col-span-4"
          style={
            {
              "--lg-a": "15 23 42",
              "--lg-b": "30 41 59",
              "--lg-c": "236 72 153",
            } as React.CSSProperties
          }
        >
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

async function WorkspaceHeader({ workspace }: { workspace: Workspace }) {
  const t = await getTranslations();
  return (
    <div
      className="liquid-glass rounded-xl p-6 flex flex-col gap-6 md:flex-row md:items-center md:justify-between"
      style={
        {
          "--lg-a": "30 41 59",
          "--lg-b": "15 23 42",
          "--lg-c": "99 102 241",
        } as React.CSSProperties
      }
    >
      <div className="flex flex-col gap-1.5">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
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

type TournamentWithCount = Tournament & { registrations_count?: number };

async function WorkspaceEventsSection({ workspaceId }: { workspaceId: number }) {
  const t = await getTranslations();
  let activeTournaments: TournamentWithCount[] = [];

  try {
    const data = await tournamentService.getActive();
    activeTournaments = (data.results as TournamentWithCount[])
      .filter((tour) => tour.workspace_id === workspaceId && isTournamentStatusActive(tour.status))
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
      <div className="flex items-center gap-2.5 mb-4">
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
        </span>
        <span className="text-[11px] font-bold tracking-[0.14em] uppercase text-emerald-400">
          {liveCount > 0 && t("statistics.liveCount", { count: liveCount })}
          {liveCount > 0 && upcomingCount > 0 && " · "}
          {upcomingCount > 0 && t("statistics.upcomingCount", { count: upcomingCount })}
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {activeTournaments.map((tour) => (
          <EventCard key={tour.id} tournament={tour} />
        ))}
      </div>
    </div>
  );
}

async function EventCard({ tournament }: { tournament: TournamentWithCount }) {
  const t = await getTranslations();
  const isLive = tournament.status === "live" || tournament.status === "playoffs";
  const statusMeta = getTournamentStatusMeta(tournament.status);

  const startDate = new Date(tournament.start_date);
  const endDate = new Date(tournament.end_date);
  const sameDay = startDate.toDateString() === endDate.toDateString();
  const dateStr = sameDay
    ? startDate.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    : `${startDate.toLocaleDateString("en-US", { month: "short", day: "numeric" })} – ${endDate.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`;

  return (
    <Link href={`/tournaments/${tournament.id}`}>
      <div className="group h-full rounded-xl border border-border/60 bg-card/50 p-4 flex flex-col gap-3 hover:bg-card hover:border-border transition-all duration-150 cursor-pointer">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {isLive ? (
              <>
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-400" />
                </span>
                <span className="text-[10px] font-bold tracking-[0.1em] uppercase text-emerald-400">
                  {t("common.live")}
                </span>
              </>
            ) : (
              <>
                <span className="h-1.5 w-1.5 rounded-full bg-amber-400 inline-block shrink-0" />
                <span className={`text-[10px] font-bold tracking-[0.1em] uppercase ${statusMeta.textClassName}`}>
                  {statusMeta.badgeLabel}
                </span>
              </>
            )}
          </div>
          {tournament.is_league && (
            <span
              className="text-[9px] font-bold tracking-[0.1em] uppercase px-1.5 py-0.5 rounded-full"
              style={{
                background: "color-mix(in srgb, var(--aqt-violet) 14%, transparent)",
                border: "1px solid color-mix(in srgb, var(--aqt-violet) 28%, transparent)",
                color: "var(--aqt-violet)",
              }}
            >
              {t("common.league")}
            </span>
          )}
        </div>

        <div className="font-display text-[17px] font-bold leading-snug text-foreground flex-1">
          {tournament.name}
        </div>

        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <Calendar className="h-3 w-3 shrink-0" />
            {dateStr}
          </div>
          <div className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <UsersIcon className="h-3 w-3 shrink-0" />
            {tournament.registrations_count ?? 0}{" "}
            {isLive ? t("common.participants") : t("common.registered")}
          </div>
        </div>

        <div className="pt-2.5 border-t border-border/50 flex justify-end">
          <span className="text-[12px] font-semibold tracking-[0.02em] text-indigo-400">
            {t("common.view")} →
          </span>
        </div>
      </div>
    </Link>
  );
}

function EventsSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="h-44 rounded-xl border border-border/60 bg-card/30 animate-pulse" />
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Stats grid
// ─────────────────────────────────────────────────────────────────────────────

async function StatsGrid({ workspaceId }: { workspaceId: number }) {
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

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      <StatisticsCard
        name={t("statistics.statTournamentsHeld")}
        value={overall.tournaments}
        icon={<Trophy className="h-4 w-4" />}
        iconClassName="bg-indigo-500/10 text-indigo-400"
      />
      <StatisticsCard
        name={t("statistics.statTeamsBalanced")}
        value={overall.teams}
        icon={<Scale className="h-4 w-4" />}
        iconClassName="bg-blue-500/10 text-blue-400"
      />
      <StatisticsCard
        name={t("statistics.statPlayersParticipated")}
        value={overall.players}
        icon={<Users className="h-4 w-4" />}
        iconClassName="bg-emerald-500/10 text-emerald-400"
      />
      <StatisticsCard
        name={t("common.champions")}
        value={overall.champions}
        icon={<Award className="h-4 w-4" />}
        iconClassName="bg-amber-500/10 text-amber-400"
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Dashboard cards
// ─────────────────────────────────────────────────────────────────────────────

async function TournamentsChartCard({ workspaceId }: { workspaceId: number }) {
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

async function TournamentsDivisionChartCard({ workspaceId }: { workspaceId: number }) {
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

async function ChampionsTableCard({ workspaceId }: { workspaceId: number }) {
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
      <ChampionsTable champions={champions.results} />
    </div>
  );
}

async function TopWinratePlayersTableCard({ workspaceId }: { workspaceId: number }) {
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
      <TopWinratePlayersTable players={players.results} />
    </div>
  );
}

async function PopularHeroesCard({ workspaceId }: { workspaceId: number }) {
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
