import React, { Suspense } from "react";
import Link from "next/link";
import { headers } from "next/headers";
import { Award, BarChart3, Calendar, Scale, Trophy, Users } from "lucide-react";

import StatisticsCard from "@/components/StatisticsCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHero, HeroCoord } from "@/components/site/PageHero";
import statisticsService from "@/services/statistics.service";
import workspaceService from "@/services/workspace.service";
import tournamentService from "@/services/tournament.service";
import {
  ChartCardSkeleton,
  StatsGridSkeleton,
  TableCardSkeleton,
} from "@/app/home-skeletons";
import {
  isTournamentStatusActive,
  getTournamentStatusMeta,
} from "@/lib/tournament-status";
import type { Tournament } from "@/types/tournament.types";
import type { Workspace } from "@/types/workspace.types";

export const dynamic = "force-dynamic";

// Deterministic hue per workspace (cycles through a palette)
const WORKSPACE_HUES = [174, 210, 38, 270, 142, 320, 0, 60];
function getWorkspaceHue(id: number): number {
  return WORKSPACE_HUES[id % WORKSPACE_HUES.length];
}

// ─────────────────────────────────────────────────────────────────────────────
// Root page
// ─────────────────────────────────────────────────────────────────────────────

export default async function Home() {
  // On a tenant (white-label) host the whole site is locked to one
  // workspace, so the cross-workspace "communities on this platform" list
  // is hidden. See middleware.ts (Task 6) for the header injection.
  const tenantMode = (await headers()).get("x-owt-host-mode") === "tenant";

  return (
    <div className="space-y-8">
      {/* Cinematic page intro */}
      <PageIntroSection tenantMode={tenantMode} />

      {/* Live / upcoming events */}
      <section>
        <Suspense fallback={<EventsSkeleton />}>
          <LiveEventsSection />
        </Suspense>
      </section>

      {/* Platform stats */}
      <section>
        <p className="mb-4 text-[11px] font-semibold tracking-[0.14em] uppercase text-muted-foreground/50">
          By the numbers
        </p>
        <Suspense fallback={<StatsGridSkeleton />}>
          <StatsGrid />
        </Suspense>
      </section>

      {/* Workspace / community cards */}
      {!tenantMode && (
        <section>
          <p className="mb-1.5 text-[11px] font-semibold tracking-[0.14em] uppercase text-muted-foreground/50">
            Workspaces
          </p>
          <h2 className="font-display text-3xl font-bold uppercase tracking-wide text-foreground mb-5">
            Communities on this platform
          </h2>
          <Suspense fallback={<CommunitiesSkeleton />}>
            <CommunitiesSection />
          </Suspense>
        </section>
      )}

      {/* Season dashboard */}
      <section className="pb-8 space-y-4">
        <div>
          <p className="mb-1.5 text-[11px] font-semibold tracking-[0.14em] uppercase text-muted-foreground/50">
            Season overview
          </p>
          <h2 className="font-display text-3xl font-bold uppercase tracking-wide text-foreground">
            Community Dashboard
          </h2>
        </div>

        {/* Full-width tournament activity chart */}
        <DashCard>
          <Suspense fallback={<ChartCardSkeleton />}>
            <TournamentActivityCard />
          </Suspense>
        </DashCard>

        {/* 3-column: division rings | champions | top winrate */}
        <div className="grid gap-4 lg:grid-cols-3">
          <DashCard>
            <Suspense fallback={<ChartCardSkeleton />}>
              <DivisionRingsCard />
            </Suspense>
          </DashCard>

          <DashCard>
            <Suspense fallback={<TableCardSkeleton />}>
              <ChampionsCard />
            </Suspense>
          </DashCard>

          <DashCard>
            <Suspense fallback={<TableCardSkeleton />}>
              <TopWinRateCard />
            </Suspense>
          </DashCard>
        </div>
      </section>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Page intro (cinematic header)
// ─────────────────────────────────────────────────────────────────────────────

function PageIntroSection({ tenantMode }: { tenantMode: boolean }) {
  return (
    <PageHero
      align="center"
      eyebrow={<HeroCoord>OWT // Overwatch Tournament Platform</HeroCoord>}
      title={
        <>
          What&apos;s happening <em>now</em>
        </>
      }
      lede={
        tenantMode
          ? "Tournaments, player stats and rankings for this community."
          : "Tournaments, player stats and rankings across all communities on the platform."
      }
      actions={
        <>
          <Button asChild size="lg" className="shadow-lg shadow-primary/20">
            <Link href="/tournaments">
              <Trophy className="mr-2 h-5 w-5" />
              Browse Tournaments
            </Link>
          </Button>
          <Button asChild variant="secondary" size="lg">
            <Link href="/tournaments/analytics">
              <BarChart3 className="mr-2 h-5 w-5" />
              Analytics
            </Link>
          </Button>
        </>
      }
    />
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Live events section
// ─────────────────────────────────────────────────────────────────────────────

type TournamentWithCount = Tournament & { registrations_count?: number };

async function LiveEventsSection() {
  let activeTournaments: TournamentWithCount[] = [];
  let workspaceMap = new Map<number, Workspace>();

  try {
    const [tournamentsData, workspaces] = await Promise.all([
      tournamentService.getActive(),
      workspaceService.getAll(),
    ]);

    activeTournaments = (tournamentsData.results as TournamentWithCount[])
      .filter((t) => isTournamentStatusActive(t.status))
      .slice(0, 6);

    workspaceMap = new Map(workspaces.map((w) => [w.id, w]));
  } catch {
    // fail silently — show empty state
  }

  const liveCount = activeTournaments.filter(
    (t) => t.status === "live" || t.status === "playoffs"
  ).length;
  const upcomingCount = activeTournaments.length - liveCount;

  if (activeTournaments.length === 0) {
    return <NoEventsState />;
  }

  return (
    <div>
      <div className="flex items-center gap-2.5 mb-4">
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
        </span>
        <span className="text-[11px] font-bold tracking-[0.14em] uppercase text-emerald-400">
          {liveCount > 0 && `${liveCount} Live`}
          {liveCount > 0 && upcomingCount > 0 && " · "}
          {upcomingCount > 0 && `${upcomingCount} Upcoming`}
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {activeTournaments.map((t) => (
          <EventCard
            key={t.id}
            tournament={t}
            workspace={workspaceMap.get(t.workspace_id)}
          />
        ))}
      </div>
    </div>
  );
}

function EventCard({
  tournament,
  workspace,
}: {
  tournament: TournamentWithCount;
  workspace?: Workspace;
}) {
  const isLive =
    tournament.status === "live" || tournament.status === "playoffs";
  const statusMeta = getTournamentStatusMeta(tournament.status);
  const hue = workspace ? getWorkspaceHue(workspace.id) : 174;

  const startDate = new Date(tournament.start_date);
  const endDate = new Date(tournament.end_date);
  const sameDay = startDate.toDateString() === endDate.toDateString();
  const dateStr = sameDay
    ? startDate.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : `${startDate.toLocaleDateString("en-US", { month: "short", day: "numeric" })} – ${endDate.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`;

  return (
    <Link href={`/tournaments/${tournament.id}`}>
      <div className="group h-full rounded-xl border border-border/60 bg-card/50 p-4 flex flex-col gap-3 hover:bg-card hover:border-border transition-all duration-150 cursor-pointer">
        {/* Status + badges row */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {isLive ? (
              <>
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-400" />
                </span>
                <span className="text-[10px] font-bold tracking-[0.1em] uppercase text-emerald-400">
                  Live
                </span>
              </>
            ) : (
              <>
                <span className="h-1.5 w-1.5 rounded-full bg-amber-400 inline-block flex-shrink-0" />
                <span
                  className={`text-[10px] font-bold tracking-[0.1em] uppercase ${statusMeta.textClassName}`}
                >
                  {statusMeta.badgeLabel}
                </span>
              </>
            )}
          </div>

          <div className="flex items-center gap-1.5">
            {tournament.is_league && (
              <span
                className="text-[9px] font-bold tracking-[0.1em] uppercase px-1.5 py-0.5 rounded-full"
                style={{
                  background: "hsl(270 70% 55% / 0.14)",
                  border: "1px solid hsl(270 70% 55% / 0.28)",
                  color: "hsl(270 60% 72%)",
                }}
              >
                League
              </span>
            )}
            {workspace && (
              <span
                className="text-[9px] font-bold tracking-[0.08em] uppercase px-1.5 py-0.5 rounded-full"
                style={{
                  background: `hsl(${hue} 72% 46% / 0.12)`,
                  border: `1px solid hsl(${hue} 72% 46% / 0.25)`,
                  color: `hsl(${hue} 72% 58%)`,
                }}
              >
                {workspace.name}
              </span>
            )}
          </div>
        </div>

        {/* Tournament name */}
        <div className="font-display text-[17px] font-bold leading-snug text-foreground flex-1">
          {tournament.name}
        </div>

        {/* Meta info */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <Calendar className="h-3 w-3 flex-shrink-0" />
            {dateStr}
          </div>
          <div className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <Users className="h-3 w-3 flex-shrink-0" />
            {tournament.registrations_count ?? 0}{" "}
            {isLive ? "participants" : "registered"}
          </div>
        </div>

        {/* Footer */}
        <div className="pt-2.5 border-t border-border/50 flex justify-end">
          <span
            className="text-[12px] font-semibold tracking-[0.02em]"
            style={{ color: `hsl(${hue} 72% 55%)` }}
          >
            View →
          </span>
        </div>
      </div>
    </Link>
  );
}

function NoEventsState() {
  return (
    <div className="flex flex-col items-center gap-3 p-8 rounded-xl border border-dashed border-border/50 max-w-sm mx-auto text-center">
      <Calendar className="h-7 w-7 text-muted-foreground/30" />
      <div>
        <p className="text-sm font-semibold text-muted-foreground mb-1">
          No active events right now
        </p>
        <p className="text-xs text-muted-foreground/50 leading-relaxed">
          Check back soon — tournaments are organized across multiple communities
          on this platform.
        </p>
      </div>
      <Button variant="outline" size="sm" asChild className="mt-1">
        <Link href="/tournaments">Browse past tournaments</Link>
      </Button>
    </div>
  );
}

function EventsSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="h-44 rounded-xl border border-border/60 bg-card/30 animate-pulse"
        />
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Communities section
// ─────────────────────────────────────────────────────────────────────────────

async function CommunitiesSection() {
  let workspaces: Workspace[] = [];
  try {
    workspaces = (await workspaceService.getAll()).filter((w) => w.is_active);
  } catch {
    return null;
  }

  if (workspaces.length === 0) return null;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
      {workspaces.map((workspace) => (
        <WorkspaceCard key={workspace.id} workspace={workspace} />
      ))}
    </div>
  );
}

function WorkspaceCard({ workspace }: { workspace: Workspace }) {
  const hue = getWorkspaceHue(workspace.id);
  const abbr = workspace.name.slice(0, 2).toUpperCase();

  return (
    <Link
      href={`/workspace/${workspace.slug}`}
      className="rounded-xl border border-border/60 bg-card/50 p-5 flex flex-col gap-3 hover:bg-card hover:border-border transition-all duration-150"
    >
      <div className="flex items-center gap-3">
        <div
          className="w-10 h-10 rounded-xl flex-shrink-0 flex items-center justify-center font-display font-extrabold text-[14px] tracking-[0.04em]"
          style={{
            background: `hsl(${hue} 72% 46% / 0.15)`,
            border: `1px solid hsl(${hue} 72% 46% / 0.3)`,
            color: `hsl(${hue} 72% 55%)`,
          }}
        >
          {abbr}
        </div>
        <div className="min-w-0">
          <div className="font-semibold text-sm text-foreground truncate">
            {workspace.name}
          </div>
          {workspace.description && (
            <div className="text-[11px] text-muted-foreground/60 mt-0.5 line-clamp-1">
              {workspace.description}
            </div>
          )}
        </div>
      </div>
    </Link>
  );
}

function CommunitiesSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="h-20 rounded-xl border border-border/60 bg-card/30 animate-pulse"
        />
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Stats grid
// ─────────────────────────────────────────────────────────────────────────────

async function StatsGrid() {
  let overall = null;
  try {
    overall = await statisticsService.getOverallStatistics({ skipWorkspace: true });
  } catch {
    // Fail silently
  }

  if (!overall) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="md:col-span-2 lg:col-span-4 border-destructive/50">
          <CardHeader>
            <CardTitle>Overall statistics</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Failed to load overall statistics.
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      <StatisticsCard
        name="Tournaments Held"
        value={overall.tournaments}
        icon={<Trophy className="h-4 w-4" />}
        iconClassName="bg-indigo-500/10 text-indigo-400"
      />
      <StatisticsCard
        name="Teams Balanced"
        value={overall.teams}
        icon={<Scale className="h-4 w-4" />}
        iconClassName="bg-blue-500/10 text-blue-400"
      />
      <StatisticsCard
        name="Players Participated"
        value={overall.players}
        icon={<Users className="h-4 w-4" />}
        iconClassName="bg-emerald-500/10 text-emerald-400"
      />
      <StatisticsCard
        name="Champions"
        value={overall.champions}
        icon={<Award className="h-4 w-4" />}
        iconClassName="bg-amber-500/10 text-amber-400"
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Dashboard primitives (matching design spec)
// ─────────────────────────────────────────────────────────────────────────────

function DashCard({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{
        background: "hsl(215 22% 7%)",
        border: "1px solid hsl(215 20% 11%)",
      }}
    >
      {children}
    </div>
  );
}

function DashCardHeader({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="px-5 py-4 border-b font-display font-bold text-[15px] uppercase tracking-[0.04em]"
      style={{ borderColor: "hsl(215 20% 10%)", color: "hsl(210 20% 88%)" }}
    >
      {children}
    </div>
  );
}

function PlaceBadge({ n }: { n: number }) {
  const map: Record<number, { bg: string; color: string }> = {
    1: { bg: "#cbb765", color: "#121009" },
    2: { bg: "#99b0cc", color: "#121009" },
    3: { bg: "#a86243", color: "#fff" },
  };
  const s = map[n] ?? { bg: "hsl(215 20% 14%)", color: "hsl(210 20% 65%)" };
  return (
    <span
      className="w-[22px] h-[22px] rounded-full shrink-0 inline-flex items-center justify-center text-[11px] font-bold"
      style={{ background: s.bg, color: s.color }}
    >
      {n}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Dashboard cards (new, matching design)
// ─────────────────────────────────────────────────────────────────────────────

async function TournamentActivityCard() {
  let visible = null;
  let max = 1;
  try {
    const data = await statisticsService.getTournaments({ skipWorkspace: true });
    if (data.length > 0) {
      visible = data.slice(-24);
      max = Math.max(...visible.map((d) => d.players_count), 1);
    }
  } catch {
    // Fail silently
  }

  if (!visible) {
    return (
      <>
        <DashCardHeader>Tournament Activity</DashCardHeader>
        <div className="px-5 py-4 text-sm text-muted-foreground">
          Failed to load data.
        </div>
      </>
    );
  }

  return (
    <>
      <DashCardHeader>Tournament Activity</DashCardHeader>
      <div className="px-5 pb-3 pt-5">
        <div className="flex items-end gap-[4px]" style={{ height: 110 }}>
          {visible.map((t, i) => (
            <div
              key={t.id}
              className="flex-1 flex flex-col justify-end"
              style={{ height: "100%" }}
            >
              <div
                style={{
                  height: `${(t.players_count / max) * 100}%`,
                  background:
                    i === visible.length - 1
                      ? "hsl(174 72% 46%)"
                      : "hsl(174 72% 46% / 0.22)",
                  borderRadius: "3px 3px 0 0",
                  minHeight: 3,
                }}
              />
            </div>
          ))}
        </div>
        <div className="flex mt-1.5">
          {visible.map((t, i) => (
            <span
              key={t.id}
              className="flex-1 text-center"
              style={{ fontSize: 9, color: "hsl(215 12% 36%)" }}
            >
              {i % Math.ceil(visible.length / 8) === 0 ? `#${t.number}` : ""}
            </span>
          ))}
        </div>
      </div>
    </>
  );
}

async function DivisionRingsCard() {
  let roles = null;
  try {
    const data = await statisticsService.getTournamentsDivision({
      skipWorkspace: true,
    });
    if (data.length > 0) {
      const mean = (vals: (number | null)[]) => {
        const nums = vals.filter((v): v is number => v != null);
        return nums.length
          ? nums.reduce((a, b) => a + b, 0) / nums.length
          : 0;
      };

      const meanTank = mean(data.map((d) => d.tank_avg_div));
      const meanDamage = mean(data.map((d) => d.damage_avg_div));
      const meanSupport = mean(data.map((d) => d.support_avg_div));
      const globalMax = Math.max(meanTank, meanDamage, meanSupport, 0.001);

      roles = [
        { label: "Tank", val: meanTank, pct: (meanTank / globalMax) * 100, color: 210 },
        { label: "Damage", val: meanDamage, pct: (meanDamage / globalMax) * 100, color: 38 },
        { label: "Support", val: meanSupport, pct: (meanSupport / globalMax) * 100, color: 174 },
      ];
    }
  } catch {
    // Fail silently
  }

  if (!roles) {
    return (
      <>
        <DashCardHeader>Avg Division by Role</DashCardHeader>
        <div className="px-5 py-4 text-sm text-muted-foreground">
          Failed to load data.
        </div>
      </>
    );
  }

  const r = 28;
  const circum = 2 * Math.PI * r;

  return (
    <>
      <DashCardHeader>Avg Division by Role</DashCardHeader>
      <div className="px-5 py-5 flex gap-4 items-start flex-wrap">
        {roles.map((role) => (
          <div
            key={role.label}
            className="flex flex-col items-center gap-2 flex-1"
            style={{ minWidth: 76 }}
          >
            <svg width="72" height="72" viewBox="0 0 72 72">
              <circle
                cx="36" cy="36" r={r}
                fill="none"
                stroke="hsl(215 20% 11%)"
                strokeWidth="7"
              />
              <circle
                cx="36" cy="36" r={r}
                fill="none"
                stroke={`hsl(${role.color} 72% 46%)`}
                strokeWidth="7"
                strokeDasharray={`${(circum * role.pct) / 100} ${circum}`}
                strokeLinecap="round"
                transform="rotate(-90 36 36)"
              />
              <text
                x="36" y="40"
                textAnchor="middle"
                fontSize="12"
                fontWeight="700"
                fontFamily="Barlow Condensed, sans-serif"
                fill={`hsl(${role.color} 72% 55%)`}
              >
                {role.val.toFixed(1)}
              </text>
            </svg>
            <span
              className="text-[12px] font-medium"
              style={{ color: "hsl(215 12% 50%)" }}
            >
              {role.label}
            </span>
          </div>
        ))}
        <p
          className="flex-[2] text-[12px] leading-relaxed self-center"
          style={{ color: "hsl(215 12% 42%)", minWidth: 90 }}
        >
          Average division rank per role across all tournaments.
        </p>
      </div>
    </>
  );
}

async function ChampionsCard() {
  let top = null;
  try {
    const data = await statisticsService.getChampions({ skipWorkspace: true });
    top = data.results.slice(0, 5);
  } catch {
    // Fail silently
  }

  if (!top) {
    return (
      <>
        <DashCardHeader>Most Championships</DashCardHeader>
        <div className="px-5 py-4 text-sm text-muted-foreground">
          Failed to load data.
        </div>
      </>
    );
  }

  return (
    <>
      <DashCardHeader>Most Championships</DashCardHeader>
      {top.map((p, i) => (
        <div
          key={p.id}
          className="flex items-center justify-between px-5 py-2.5 text-[13px] border-b last:border-b-0 hover:bg-white/[0.02] transition-colors"
          style={{
            borderColor: "hsl(215 20% 9%)",
            color: "hsl(210 20% 80%)",
          }}
        >
          <div className="flex items-center gap-2.5">
            <PlaceBadge n={i + 1} />
            <Link
              href={`/users/${p.name.replace("#", "-")}`}
              className="font-semibold hover:text-foreground transition-colors"
            >
              {p.name}
            </Link>
          </div>
          <span
            className="font-bold font-mono min-w-[28px] text-right"
            style={{ color: "hsl(174 72% 55%)" }}
          >
            {p.value}×
          </span>
        </div>
      ))}
    </>
  );
}

async function TopWinRateCard() {
  let top = null;
  try {
    const data = await statisticsService.getTopWinratePlayers({
      skipWorkspace: true,
    });
    top = data.results.slice(0, 5);
  } catch {
    // Fail silently
  }

  if (!top) {
    return (
      <>
        <DashCardHeader>Top Win Rate</DashCardHeader>
        <div className="px-5 py-4 text-sm text-muted-foreground">
          Failed to load data.
        </div>
      </>
    );
  }

  return (
    <>
      <DashCardHeader>Top Win Rate</DashCardHeader>
      {top.map((p, i) => (
        <div
          key={p.id}
          className="flex items-center justify-between px-5 py-2.5 text-[13px] border-b last:border-b-0 hover:bg-white/[0.02] transition-colors"
          style={{
            borderColor: "hsl(215 20% 9%)",
            color: "hsl(210 20% 80%)",
          }}
        >
          <div className="flex items-center gap-2.5">
            <span
              className="font-mono text-[12px] min-w-[22px]"
              style={{ color: "hsl(215 12% 38%)" }}
            >
              #{i + 1}
            </span>
            <Link
              href={`/users/${p.name.replace("#", "-")}`}
              className="font-semibold hover:text-foreground transition-colors"
            >
              {p.name}
            </Link>
          </div>
          <span
            className="font-bold font-mono min-w-[44px] text-right"
            style={{ color: "hsl(142 70% 55%)" }}
          >
            {(p.value * 100).toFixed(1)}%
          </span>
        </div>
      ))}
    </>
  );
}
