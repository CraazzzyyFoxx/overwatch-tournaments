"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Swords, Zap, ZapOff, Plus, Skull, Crosshair } from "lucide-react";
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

type Item =
  | { kind: "kill"; time: number; fight: number; kill: KillFeedEntry }
  | { kind: "event"; time: number; event: MatchTimelineEvent };

interface FightScore {
  home: number;
  away: number;
}

interface RoundData {
  round: number;
  items: Item[];
  fightScores: Map<number, FightScore>;
  /** Match-wide fight id → 1-based local index within this round (for display). */
  fightOrder: Map<number, number>;
  home: number;
  away: number;
  multiFight: boolean;
}

/** Thin teal↔rose split bar for a kill tally (home vs away). */
const ScoreSplit = ({ home, away }: { home: number; away: number }) => {
  const total = home + away;
  const homePct = total > 0 ? (home / total) * 100 : 50;
  const homeWins = home > away;
  const awayWins = away > home;
  return (
    <div className="flex items-center gap-2">
      <span
        className="aqt-tnum text-[12px]"
        style={{ color: "var(--aqt-teal)", fontWeight: homeWins ? 700 : 500, opacity: homeWins ? 1 : 0.7 }}
      >
        {home}
      </span>
      <div className="flex h-[5px] w-16 overflow-hidden rounded-full bg-[color:var(--aqt-rose)]">
        <div style={{ width: `${homePct}%`, background: "var(--aqt-teal)" }} />
      </div>
      <span
        className="aqt-tnum text-[12px]"
        style={{ color: "var(--aqt-rose)", fontWeight: awayWins ? 700 : 500, opacity: awayWins ? 1 : 0.7 }}
      >
        {away}
      </span>
    </div>
  );
};

const MatchKillFeedTimeline = ({ matchId, home, away }: MatchKillFeedTimelineProps) => {
  const t = useTranslations();
  const [data, setData] = useState<MatchKillFeed | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    // Initial state is "loading"; state is only set from the async callbacks.
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
      for (const player of team.players) map.set(player.user_id, player.name.split("#")[0]);
    }
    return map;
  }, [home, away]);

  const homeTeamId = home.id;
  const nameOf = (userId: number) => nameByUserId.get(userId) ?? "—";
  const sideOf = (teamId: number): Side => (teamId === homeTeamId ? "home" : "away");

  const rounds = useMemo<RoundData[]>(() => {
    if (!data) return [];
    const byRound = new Map<number, RoundData>();
    const ensure = (round: number): RoundData => {
      const existing = byRound.get(round);
      if (existing) return existing;
      const created: RoundData = {
        round,
        items: [],
        fightScores: new Map(),
        fightOrder: new Map(),
        home: 0,
        away: 0,
        multiFight: false
      };
      byRound.set(round, created);
      return created;
    };
    // kill_feed `round` is a 1-indexed real round (0 = events before the first
    // RoundStart marker, i.e. lead-up to round 1 — NOT a whole-match aggregate).
    // Fold that pre-round bucket into round 1 so we don't render a phantom round.
    const roundOf = (raw: number) => Math.max(raw, 1);
    for (const kill of data.kills) {
      const block = ensure(roundOf(kill.round));
      block.items.push({ kind: "kill", time: kill.time, fight: kill.fight, kill });
      // Inline side check (not the sideOf closure) so the memo's only deps are data + homeTeamId.
      const side: Side = kill.killer_team_id === homeTeamId ? "home" : "away";
      if (side === "home") block.home += 1;
      else block.away += 1;
      const score = block.fightScores.get(kill.fight) ?? { home: 0, away: 0 };
      if (side === "home") score.home += 1;
      else score.away += 1;
      block.fightScores.set(kill.fight, score);
    }
    for (const event of data.events) {
      ensure(roundOf(event.round)).items.push({ kind: "event", time: event.time, event });
    }
    for (const block of byRound.values()) {
      block.items.sort((a, b) => a.time - b.time);
      block.multiFight = block.fightScores.size > 1;
      // Renumber match-wide fight ids to a local 1..K index so each round reads
      // "Fight 1, 2, 3" instead of jumping (fights don't reset per round upstream).
      [...block.fightScores.keys()]
        .sort((a, b) => a - b)
        .forEach((fightId, index) => block.fightOrder.set(fightId, index + 1));
    }
    return [...byRound.values()].sort((a, b) => a.round - b.round);
  }, [data, homeTeamId]);

  const multiRound = rounds.length > 1;

  const totalKills = data?.kills.length ?? 0;

  const legend = (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[color:var(--aqt-fg-dim)]">
      <span className="inline-flex items-center gap-1">
        <Zap className="h-3 w-3 text-[color:var(--aqt-violet)]" /> {t("matches.timeline.ultStart")}
      </span>
      <span className="inline-flex items-center gap-1">
        <span
          className="rounded px-1 text-[8px] font-bold uppercase leading-[1.4]"
          style={{ color: "var(--aqt-violet)", background: "hsl(270 70% 62% / 0.16)" }}
        >
          ULT
        </span>
        {t("matches.timeline.ultKill")}
      </span>
      <span className="inline-flex items-center gap-1">
        <ZapOff className="h-3 w-3 text-[color:var(--aqt-violet)] opacity-60" /> {t("matches.timeline.ultEnd")}
      </span>
      <span className="inline-flex items-center gap-1">
        <Crosshair className="h-3 w-3 text-[color:var(--aqt-amber)]" /> {t("matches.timeline.critical")}
      </span>
      <span className="inline-flex items-center gap-1">
        <Skull className="h-3 w-3 text-[color:var(--aqt-fg-muted)]" /> {t("matches.timeline.environmental")}
      </span>
      <span className="inline-flex items-center gap-1">
        <Plus className="h-3 w-3 text-[color:var(--aqt-support)]" /> {t("matches.timeline.resurrect")}
      </span>
    </div>
  );

  const renderKill = (kill: KillFeedEntry, key: string) => {
    const killerSide = sideOf(kill.killer_team_id);
    const isUltKill = kill.ability === "Ultimate";
    return (
      <div
        key={key}
        className="flex items-center gap-2 py-[5px] pl-3"
        style={{
          borderLeft: `2px solid ${sideColor(killerSide)}`,
          // Ult kills get a faint violet wash so they stand out from normal trades.
          background: isUltKill ? "hsl(270 70% 62% / 0.07)" : undefined
        }}
      >
        <span className="aqt-mono w-8 shrink-0 text-[10.5px] text-[color:var(--aqt-fg-faint)]">
          {formatClock(kill.time)}
        </span>
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          <HeroImage hero={kill.killer_hero} size="sm" />
          <span className="truncate text-[12.5px] font-semibold" style={{ color: sideColor(killerSide) }}>
            {nameOf(kill.killer_user_id)}
          </span>
        </div>
        <Swords className="h-3.5 w-3.5 shrink-0 text-[color:var(--aqt-fg-dim)]" aria-hidden="true" />
        <div className="flex min-w-0 flex-1 items-center justify-end gap-1.5">
          <span className="truncate text-right text-[12px] text-[color:var(--aqt-fg-dim)]">
            {nameOf(kill.victim_user_id)}
          </span>
          <span className="opacity-70">
            <HeroImage hero={kill.victim_hero} size="sm" />
          </span>
        </div>
        <div className="flex min-w-[52px] shrink-0 items-center justify-end gap-1">
          {isUltKill ? (
            <span
              className="rounded px-1 py-px text-[9px] font-bold uppercase tracking-wide"
              style={{
                color: "var(--aqt-violet)",
                background: "hsl(270 70% 62% / 0.16)",
                border: "1px solid hsl(270 70% 62% / 0.3)"
              }}
              aria-label="ultimate kill"
            >
              ULT
            </span>
          ) : null}
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

  const renderEvent = (event: MatchTimelineEvent, key: string) => {
    const side = sideOf(event.team_id);
    const isRez = event.name === "mercy_rez";
    const isUltEnd = event.name === "ultimate_end";
    const Icon = isRez ? Plus : isUltEnd ? ZapOff : Zap;
    const color = isRez ? "var(--aqt-support)" : "var(--aqt-violet)";
    const label = isRez
      ? t("matches.timeline.resurrect")
      : isUltEnd
        ? t("matches.timeline.ultEnd")
        : t("matches.timeline.ultStart");
    return (
      <div
        key={key}
        className="flex items-center gap-2 py-[3px] pl-3"
        // Ult end is dimmed so the start→end bracket around ult kills reads clearly.
        style={{ borderLeft: "2px solid transparent", opacity: isUltEnd ? 0.6 : 1 }}
      >
        <span className="aqt-mono w-8 shrink-0 text-[10.5px] text-[color:var(--aqt-fg-faint)]">
          {formatClock(event.time)}
        </span>
        <Icon className="h-3 w-3 shrink-0" style={{ color }} aria-hidden="true" />
        {event.hero ? (
          <span className="opacity-80">
            <HeroImage hero={event.hero} size="sm" />
          </span>
        ) : null}
        <span className="truncate text-[11.5px] font-medium" style={{ color: sideColor(side) }}>
          {nameOf(event.user_id)}
        </span>
        <span className="text-[10px] uppercase tracking-[0.08em] text-[color:var(--aqt-fg-dim)]">{label}</span>
        {isRez && event.related_user_id != null ? (
          <span className="truncate text-[10.5px] text-[color:var(--aqt-fg-faint)]">→ {nameOf(event.related_user_id)}</span>
        ) : null}
      </div>
    );
  };

  return (
    <div className="rounded-[12px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="aqt-mono text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
          {t("matches.timeline.title")}
        </span>
        {status === "ready" && totalKills > 0 ? legend : null}
      </div>

      {status === "loading" ? (
        <div className="py-8 text-center text-[13px] text-[color:var(--aqt-fg-dim)]">
          {t("matches.timeline.loading")}
        </div>
      ) : null}
      {status === "error" ? (
        <div className="py-8 text-center text-[13px] text-[color:var(--aqt-rose)]">{t("matches.timeline.error")}</div>
      ) : null}
      {status === "ready" && totalKills === 0 ? (
        <div className="py-8 text-center text-[13px] text-[color:var(--aqt-fg-dim)]">{t("matches.timeline.empty")}</div>
      ) : null}

      {status === "ready" && totalKills > 0 ? (
        <div className="flex max-h-[600px] flex-col gap-5 overflow-y-auto pr-1">
          {rounds.map((block) => (
              <div key={block.round}>
                {/* Header: per-round kill score. Round label only when the match
                    actually has more than one round (else it's a single feed). */}
                <div className="mb-2 flex items-center justify-between gap-3 border-b border-[color:var(--aqt-border)] pb-1.5">
                  <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-muted)]">
                    {multiRound ? t("matches.round", { round: block.round }) : ""}
                  </span>
                  <ScoreSplit home={block.home} away={block.away} />
                </div>

                <div className="flex flex-col">
                  {block.items.map((item, i) => {
                    if (item.kind === "event") return renderEvent(item.event, `e-${i}`);
                    // Kill: emit a fight divider when the fight changes (multi-fight rounds only).
                    // Look back for the previous kill's fight (no mutable running state in render).
                    const prevKill = block.items
                      .slice(0, i)
                      .reverse()
                      .find((x): x is Extract<Item, { kind: "kill" }> => x.kind === "kill");
                    const showFight = block.multiFight && (!prevKill || prevKill.fight !== item.fight);
                    const fightScore = block.fightScores.get(item.fight);
                    return (
                      <React.Fragment key={`k-${i}`}>
                        {showFight ? (
                          <div className="mb-0.5 mt-2 flex items-center gap-2 first:mt-0">
                            <span className="aqt-mono text-[9.5px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">
                              {t("matches.timeline.fight", { n: block.fightOrder.get(item.fight) ?? item.fight })}
                            </span>
                            <span className="aqt-mono text-[9.5px] text-[color:var(--aqt-fg-faint)]">
                              {formatClock(item.time)}
                            </span>
                            <div className="h-px flex-1 bg-[color:var(--aqt-border)]" />
                            {fightScore ? (
                              <span className="aqt-tnum text-[10px]">
                                <span style={{ color: "var(--aqt-teal)" }}>{fightScore.home}</span>
                                <span className="text-[color:var(--aqt-fg-faint)]">–</span>
                                <span style={{ color: "var(--aqt-rose)" }}>{fightScore.away}</span>
                              </span>
                            ) : null}
                          </div>
                        ) : null}
                        {renderKill(item.kill, `kr-${i}`)}
                      </React.Fragment>
                    );
                  })}
                </div>
              </div>
            ))}
        </div>
      ) : null}
    </div>
  );
};

export default MatchKillFeedTimeline;
