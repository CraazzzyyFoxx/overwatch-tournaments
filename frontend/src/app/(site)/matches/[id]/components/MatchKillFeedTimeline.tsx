"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Swords, Sparkles, Plus, Skull, Crosshair } from "lucide-react";
import { TeamWithStats } from "@/types/team.types";
import { KillFeedEntry, MatchKillFeed, MatchTimelineEvent } from "@/types/killfeed.types";
import encounterService from "@/services/encounter.service";
import HeroImage from "@/components/hero/HeroImage";

interface MatchKillFeedTimelineProps {
  matchId: number;
  home: TeamWithStats;
  away: TeamWithStats;
}

type Side = "home" | "away";

const sideColor = (side: Side) => (side === "home" ? "var(--aqt-teal)" : "var(--aqt-rose)");

const formatClock = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
};

interface RoundBlock {
  round: number;
  kills: KillFeedEntry[];
  events: MatchTimelineEvent[];
}

/** Cumulative home−away kill differential across a round, as an inline sparkline. */
const MomentumSpark = ({ kills, sideOf }: { kills: KillFeedEntry[]; sideOf: (teamId: number) => Side }) => {
  if (kills.length < 2) return null;
  const width = 132;
  const height = 26;
  // Cumulative home−away kill differential, computed functionally (no mutable
  // running total) so the render stays side-effect free.
  const deltas = kills.map((kill) => (sideOf(kill.killer_team_id) === "home" ? 1 : -1));
  const points = deltas.map((_, i) => ({
    x: i,
    y: deltas.slice(0, i + 1).reduce((sum, d) => sum + d, 0)
  }));
  const maxAbs = Math.max(1, ...points.map((p) => Math.abs(p.y)));
  const last = points[points.length - 1].y;
  const toX = (x: number) => (x / (points.length - 1)) * (width - 2) + 1;
  const toY = (y: number) => height / 2 - (y / maxAbs) * (height / 2 - 2);
  const path = points.map((p) => `${toX(p.x).toFixed(1)},${toY(p.y).toFixed(1)}`).join(" ");

  return (
    <svg width={width} height={height} className="shrink-0" aria-hidden="true">
      <line
        x1={1}
        y1={height / 2}
        x2={width - 1}
        y2={height / 2}
        stroke="var(--aqt-border-2)"
        strokeWidth={1}
        strokeDasharray="2 2"
      />
      <polyline
        points={path}
        fill="none"
        stroke={last === 0 ? "var(--aqt-fg-dim)" : sideColor(last > 0 ? "home" : "away")}
        strokeWidth={1.6}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
};

const KillRow = ({
  kill,
  sideOf,
  nameOf
}: {
  kill: KillFeedEntry;
  sideOf: (teamId: number) => Side;
  nameOf: (userId: number) => string;
}) => {
  const killerSide = sideOf(kill.killer_team_id);
  const isUlt = kill.ability === "Ultimate";
  return (
    <div
      className="flex items-center gap-2.5 py-1.5 pl-2.5"
      style={{ borderLeft: `2px solid ${sideColor(killerSide)}` }}
    >
      <span className="aqt-mono w-9 shrink-0 text-[11px] text-[color:var(--aqt-fg-faint)]">
        {formatClock(kill.time)}
      </span>
      <div className="flex min-w-0 flex-1 items-center gap-1.5">
        <HeroImage hero={kill.killer_hero} size="sm" />
        <span
          className="truncate text-[12.5px] font-semibold"
          style={{ color: sideColor(killerSide) }}
        >
          {nameOf(kill.killer_user_id)}
        </span>
      </div>
      <Swords className="h-3.5 w-3.5 shrink-0 text-[color:var(--aqt-fg-dim)]" aria-hidden="true" />
      <div className="flex min-w-0 flex-1 items-center justify-end gap-1.5">
        <span className="truncate text-right text-[12.5px] text-[color:var(--aqt-fg-muted)] line-through decoration-[color:var(--aqt-fg-faint)]/60">
          {nameOf(kill.victim_user_id)}
        </span>
        <HeroImage hero={kill.victim_hero} size="sm" />
      </div>
      <div className="flex w-14 shrink-0 items-center justify-end gap-1">
        {isUlt ? <Sparkles className="h-3.5 w-3.5 text-[color:var(--aqt-violet)]" aria-label="ultimate" /> : null}
        {kill.is_critical_hit ? (
          <Crosshair className="h-3.5 w-3.5 text-[color:var(--aqt-amber)]" aria-label="critical" />
        ) : null}
        {kill.is_environmental ? (
          <Skull className="h-3.5 w-3.5 text-[color:var(--aqt-fg-muted)]" aria-label="environmental" />
        ) : null}
      </div>
    </div>
  );
};

const EventRow = ({
  event,
  sideOf,
  nameOf
}: {
  event: MatchTimelineEvent;
  sideOf: (teamId: number) => Side;
  nameOf: (userId: number) => string;
}) => {
  const t = useTranslations();
  const side = sideOf(event.team_id);
  const isRez = event.name === "mercy_rez";
  const Icon = isRez ? Plus : Sparkles;
  const iconColor = isRez ? "var(--aqt-support)" : "var(--aqt-violet)";
  const label = isRez ? t("matches.timeline.resurrect") : t("matches.timeline.ultimate");
  return (
    <div className="flex items-center gap-2.5 py-1 pl-2.5" style={{ borderLeft: "2px solid transparent" }}>
      <span className="aqt-mono w-9 shrink-0 text-[11px] text-[color:var(--aqt-fg-faint)]">
        {formatClock(event.time)}
      </span>
      <Icon className="h-3.5 w-3.5 shrink-0" style={{ color: iconColor }} aria-hidden="true" />
      {event.hero ? <HeroImage hero={event.hero} size="sm" /> : null}
      <span className="truncate text-[12px] font-medium" style={{ color: sideColor(side) }}>
        {nameOf(event.user_id)}
      </span>
      <span className="text-[11px] uppercase tracking-[0.08em] text-[color:var(--aqt-fg-dim)]">{label}</span>
      {isRez && event.related_user_id != null ? (
        <span className="truncate text-[11px] text-[color:var(--aqt-fg-faint)]">
          → {nameOf(event.related_user_id)}
        </span>
      ) : null}
    </div>
  );
};

const MatchKillFeedTimeline = ({ matchId, home, away }: MatchKillFeedTimelineProps) => {
  const t = useTranslations();
  const [data, setData] = useState<MatchKillFeed | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    // Initial state is "loading"; state is only set from the async callbacks
    // (never synchronously in the effect body) so re-renders don't cascade.
    let active = true;
    encounterService
      .getMatchKillFeed(matchId)
      .then((feed) => {
        if (!active) return;
        setData(feed);
        setStatus("ready");
      })
      .catch(() => {
        if (active) setStatus("error");
      });
    return () => {
      active = false;
    };
  }, [matchId]);

  const nameByUserId = useMemo(() => {
    const map = new Map<number, string>();
    for (const team of [home, away]) {
      for (const player of team.players) {
        map.set(player.user_id, player.name.split("#")[0]);
      }
    }
    return map;
  }, [home, away]);

  const homeTeamId = home.id;
  const nameOf = (userId: number) => nameByUserId.get(userId) ?? "—";
  const sideOf = (teamId: number): Side => (teamId === homeTeamId ? "home" : "away");

  const rounds = useMemo<RoundBlock[]>(() => {
    if (!data) return [];
    const byRound = new Map<number, RoundBlock>();
    const ensure = (round: number) => {
      let block = byRound.get(round);
      if (!block) {
        block = { round, kills: [], events: [] };
        byRound.set(round, block);
      }
      return block;
    };
    for (const kill of data.kills) ensure(kill.round).kills.push(kill);
    for (const event of data.events) ensure(event.round).events.push(event);
    return [...byRound.values()].sort((a, b) => a.round - b.round);
  }, [data]);

  const totalKills = data?.kills.length ?? 0;

  return (
    <div className="rounded-[12px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="aqt-mono text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
          {t("matches.timeline.title")}
        </span>
        {status === "ready" && totalKills > 0 ? (
          <span className="aqt-mono text-[10px] text-[color:var(--aqt-fg-faint)]">
            {t("matches.timeline.killCount", { count: totalKills })}
          </span>
        ) : null}
      </div>

      {status === "loading" ? (
        <div className="py-8 text-center text-[13px] text-[color:var(--aqt-fg-dim)]">
          {t("matches.timeline.loading")}
        </div>
      ) : null}

      {status === "error" ? (
        <div className="py-8 text-center text-[13px] text-[color:var(--aqt-rose)]">
          {t("matches.timeline.error")}
        </div>
      ) : null}

      {status === "ready" && totalKills === 0 ? (
        <div className="py-8 text-center text-[13px] text-[color:var(--aqt-fg-dim)]">
          {t("matches.timeline.empty")}
        </div>
      ) : null}

      {status === "ready" && totalKills > 0 ? (
        <div className="flex max-h-[560px] flex-col gap-4 overflow-y-auto pr-1">
          {rounds.map((block) => {
            const items = [
              ...block.kills.map((kill) => ({ kind: "kill" as const, time: kill.time, kill })),
              ...block.events.map((event) => ({ kind: "event" as const, time: event.time, event }))
            ].sort((a, b) => a.time - b.time);

            return (
              <div key={block.round}>
                <div className="mb-1.5 flex items-center justify-between gap-3 border-b border-[color:var(--aqt-border)] pb-1">
                  <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-muted)]">
                    {block.round === 0 ? t("matches.allMatch") : t("matches.round", { round: block.round })}
                  </span>
                  <MomentumSpark kills={block.kills} sideOf={sideOf} />
                </div>
                <div className="flex flex-col">
                  {items.map((item, i) =>
                    item.kind === "kill" ? (
                      <KillRow key={`k-${i}`} kill={item.kill} sideOf={sideOf} nameOf={nameOf} />
                    ) : (
                      <EventRow key={`e-${i}`} event={item.event} sideOf={sideOf} nameOf={nameOf} />
                    )
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
};

export default MatchKillFeedTimeline;
