import React, { Suspense } from "react";
import Link from "next/link";
import { Award, Map as MapIcon, Percent, Scale, Trophy, Users } from "lucide-react";

import StatisticsCard from "@/components/StatisticsCard";
import TournamentsChart from "@/components/TournamentsChart";
import TournamentsDivisionChart from "@/components/TournamentsDivisionChart";
import statisticsService from "@/services/statistics.service";
import type {
  PlayerStatistics,
  TournamentDivisionStatistics,
  TournamentStatistics,
} from "@/types/statistics.types";
import { ChartCardSkeleton, StatsGridSkeleton, TableCardSkeleton } from "@/app/home-skeletons";

export const dynamic = "force-dynamic";

const LEADERBOARD_SIZE = 15;

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────

export default function StatisticsPage() {
  return (
    <div className="space-y-8">
      <header>
        <p className="mb-2 text-[11px] font-semibold tracking-[0.14em] uppercase text-muted-foreground/50">
          Platform statistics
        </p>
        <h1 className="font-display text-3xl font-bold uppercase tracking-wide text-foreground">
          All-time leaderboards &amp; trends
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          Aggregate numbers across every tournament: how the field has grown, the average
          division per role over time, and the players who top the championship, win-rate and
          maps-won boards.
        </p>
      </header>

      <section>
        <Suspense fallback={<StatsGridSkeleton />}>
          <OverallStats />
        </Suspense>
      </section>

      <section className="space-y-4">
        <SectionLabel>Trends over time</SectionLabel>
        <Suspense fallback={<ChartCardSkeleton />}>
          <ActivityTrendCard />
        </Suspense>
        <Suspense fallback={<ChartCardSkeleton />}>
          <DivisionTrendCard />
        </Suspense>
      </section>

      <section className="space-y-4">
        <SectionLabel>Leaderboards</SectionLabel>
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

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[11px] font-semibold tracking-[0.14em] uppercase text-muted-foreground/50">
      {children}
    </p>
  );
}

function DashCard({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: "var(--aqt-bg-2)", border: "1px solid var(--aqt-border)" }}
    >
      {children}
    </div>
  );
}

function DashCardHeader({ icon, children }: { icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div
      className="flex items-center gap-2 px-5 py-4 border-b font-display font-bold text-[15px] uppercase tracking-[0.04em]"
      style={{ borderColor: "var(--aqt-border)", color: "var(--aqt-fg)" }}
    >
      {icon}
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
  const s = map[n] ?? { bg: "var(--aqt-border-2)", color: "var(--aqt-fg-muted)" };
  return (
    <span
      className="w-[22px] h-[22px] rounded-full shrink-0 inline-flex items-center justify-center text-[11px] font-bold tabular-nums"
      style={{ background: s.bg, color: s.color }}
    >
      {n}
    </span>
  );
}

function ErrorBody({ message }: { message: string }) {
  return <div className="px-5 py-4 text-sm text-muted-foreground">{message}</div>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Overall KPI strip
// ─────────────────────────────────────────────────────────────────────────────

async function OverallStats() {
  let overall = null;
  try {
    overall = await statisticsService.getOverallStatistics({ skipWorkspace: true });
  } catch {
    overall = null;
  }

  if (!overall) {
    return (
      <DashCard>
        <ErrorBody message="Failed to load overall statistics." />
      </DashCard>
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
// Trend charts (full recharts versions, not on the home summary)
// ─────────────────────────────────────────────────────────────────────────────

async function ActivityTrendCard() {
  let data: TournamentStatistics[] | null = null;
  try {
    data = await statisticsService.getTournaments({ skipWorkspace: true });
  } catch {
    data = null;
  }

  if (!data || data.length === 0) {
    return (
      <DashCard>
        <DashCardHeader>Tournament activity</DashCardHeader>
        <ErrorBody message={data ? "No tournament data yet." : "Failed to load tournament trends."} />
      </DashCard>
    );
  }
  return <TournamentsChart data={data} />;
}

async function DivisionTrendCard() {
  let data: TournamentDivisionStatistics[] | null = null;
  try {
    data = await statisticsService.getTournamentsDivision({ skipWorkspace: true });
  } catch {
    data = null;
  }

  if (!data || data.length === 0) {
    return (
      <DashCard>
        <DashCardHeader>Average division by role</DashCardHeader>
        <ErrorBody message={data ? "No division data yet." : "Failed to load division trends."} />
      </DashCard>
    );
  }
  return <TournamentsDivisionChart data={data} />;
}

// ─────────────────────────────────────────────────────────────────────────────
// Leaderboards
// ─────────────────────────────────────────────────────────────────────────────

function LeaderboardCard({
  title,
  icon,
  rows,
  format,
  accent,
}: {
  title: string;
  icon: React.ReactNode;
  rows: PlayerStatistics[];
  format: (value: number) => string;
  accent: string;
}) {
  return (
    <DashCard>
      <DashCardHeader icon={icon}>{title}</DashCardHeader>
      {rows.length === 0 ? (
        <ErrorBody message="No data yet." />
      ) : (
        rows.map((player, index) => (
          <div
            key={player.id}
            className="flex items-center justify-between px-5 py-2.5 text-[13px] border-b last:border-b-0 hover:bg-white/[0.02] transition-colors"
            style={{ borderColor: "var(--aqt-border)", color: "var(--aqt-fg)" }}
          >
            <div className="flex items-center gap-2.5 min-w-0">
              {index < 3 ? (
                <PlaceBadge n={index + 1} />
              ) : (
                <span
                  className="font-mono text-[12px] min-w-[22px] text-center"
                  style={{ color: "var(--aqt-fg-dim)" }}
                >
                  #{index + 1}
                </span>
              )}
              <Link
                href={`/users/${player.name.replace("#", "-")}`}
                className="font-semibold truncate hover:text-foreground transition-colors"
                title={player.name}
              >
                {player.name}
              </Link>
            </div>
            <span className="font-bold font-mono min-w-[44px] text-right" style={{ color: accent }}>
              {format(player.value)}
            </span>
          </div>
        ))
      )}
    </DashCard>
  );
}

async function ChampionsLeaderboard() {
  let rows: PlayerStatistics[] = [];
  try {
    rows = (await statisticsService.getChampions({ skipWorkspace: true })).results.slice(
      0,
      LEADERBOARD_SIZE,
    );
  } catch {
    rows = [];
  }
  return (
    <LeaderboardCard
      title="Most championships"
      icon={<Trophy className="h-4 w-4 text-amber-400" />}
      rows={rows}
      format={(v) => `${v}×`}
      accent="var(--aqt-teal)"
    />
  );
}

async function WinRateLeaderboard() {
  let rows: PlayerStatistics[] = [];
  try {
    rows = (await statisticsService.getTopWinratePlayers({ skipWorkspace: true })).results.slice(
      0,
      LEADERBOARD_SIZE,
    );
  } catch {
    rows = [];
  }
  return (
    <LeaderboardCard
      title="Top win rate"
      icon={<Percent className="h-4 w-4 text-emerald-400" />}
      rows={rows}
      format={(v) => `${(v * 100).toFixed(1)}%`}
      accent="var(--aqt-emerald)"
    />
  );
}

async function WonMapsLeaderboard() {
  let rows: PlayerStatistics[] = [];
  try {
    rows = (await statisticsService.getTopWonMapsPlayers({ skipWorkspace: true })).results.slice(
      0,
      LEADERBOARD_SIZE,
    );
  } catch {
    rows = [];
  }
  return (
    <LeaderboardCard
      title="Most maps won"
      icon={<MapIcon className="h-4 w-4 text-blue-400" />}
      rows={rows}
      format={(v) => `${v}`}
      accent="var(--aqt-blue)"
    />
  );
}
