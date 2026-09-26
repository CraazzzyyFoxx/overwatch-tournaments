import React from "react";

import { CardHeader } from "@/components/ui/card";
import { PageStateCard } from "@/components/ui/page-state-card";
import { PlaceBadge } from "@/components/ui/place-badge";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import type { PlayerStatistics } from "@/types/statistics.types";

export function DashHeader({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <CardHeader className="border-b border-border px-5 py-4 font-display text-ui font-bold uppercase tracking-[0.04em] text-foreground">
      {children}
    </CardHeader>
  );
}

/**
 * Header + explained failure/empty body for a dashboard card. `error` is a
 * genuine fetch failure; `empty` is a successful request whose (workspace
 * scoped) result set is empty — e.g. a fresh tenant community with no finished
 * tournaments yet. Border and background are dropped because the surrounding
 * `Card` already draws them.
 */
export function DashCardState({
  title,
  state
}: Readonly<{
  title: string;
  state: "error" | "empty";
}>) {
  return (
    <>
      <DashHeader>{title}</DashHeader>
      <PageStateCard state={state} className="border-0 bg-transparent" />
    </>
  );
}

/**
 * Body shared by the champions and win-rate dashboard cards — title, error
 * / empty state, then a ranked list. The two cards differ only in metric
 * formatting and accent.
 */
export function TopListCard({
  title,
  top,
  valueFormatter,
  accent
}: Readonly<{
  title: string;
  top: PlayerStatistics[] | null;
  valueFormatter: (value: number) => string;
  accent: string;
}>) {
  if (!top) {
    return <DashCardState title={title} state="error" />;
  }

  if (top.length === 0) {
    return <DashCardState title={title} state="empty" />;
  }

  return (
    <>
      <DashHeader>{title}</DashHeader>
      {top.map((player, i) => (
        <LeaderboardRow
          key={player.id}
          rank={i + 1}
          name={player.name}
          value={valueFormatter(player.value)}
          accent={accent}
        />
      ))}
    </>
  );
}

/**
 * One leaderboard row, shared by the championships and win-rate cards — they
 * used to be the same markup pasted twice with a different rank treatment.
 */
function LeaderboardRow({
  rank,
  name,
  value,
  accent
}: Readonly<{
  rank: number;
  name: string;
  value: string;
  accent: string;
}>) {
  return (
    <div
      className="flex items-center justify-between px-5 py-2.5 text-caption border-b last:border-b-0 hover:bg-[color:var(--aqt-overlay-2)] transition-colors"
      style={{
        borderColor: "var(--aqt-border)",
        color: "var(--aqt-fg-muted)"
      }}
    >
      <div className="flex items-center gap-2.5 min-w-0">
        <PlaceBadge place={rank} />
        <HoverPrefetchLink
          href={`/users/${name.replace("#", "-")}`}
          className="font-semibold truncate rounded-sm transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
        >
          {name}
        </HoverPrefetchLink>
      </div>
      <span className="font-bold tabular-nums min-w-[44px] text-right" style={{ color: accent }}>
        {value}
      </span>
    </div>
  );
}
