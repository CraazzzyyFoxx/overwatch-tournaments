"use client";

import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ArrowRight, Crosshair, Plus, RotateCw, Skull, Zap, ZapOff } from "lucide-react";
import type { MatchWithStats } from "@/types/encounter.types";
import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { splitHandle } from "@/lib/player";
import { cn } from "@/lib/utils";
import type { FightFocus } from "./MatchStats";
import {
  readFights,
  timelineRound,
  type TimelineFight,
  type TimelineKill,
  type TimelineMark,
  type TimelineSide
} from "./timeline";
import { useMatchTimeline } from "./useMatchTimeline";
import type { OwTeam } from "./view";

interface KillFeedTimelineProps {
  matchId: number;
  /** The match's observed members: the timeline names actors by workspace member. */
  members: MatchWithStats["statistics"]["members"];
  home: OwTeam;
  away: OwTeam;
  /** 0 is the whole map; otherwise only this round is drawn. */
  round: number;
  /** A request to bring one fight into view (the breakdown's links). */
  focus: FightFocus | null;
}

// Literal class strings, so Tailwind sees them.
const SEAT_TEXT: Record<TimelineSide, string> = {
  home: "text-[color:var(--aqt-teal)]",
  away: "text-[color:var(--aqt-rose)]"
};
const SEAT_FILL: Record<TimelineSide, string> = { home: "var(--aqt-teal)", away: "var(--aqt-rose)" };
const FAINT_TEXT = "text-[color:var(--aqt-fg-faint)]";
const MUTED_TEXT = "text-[color:var(--aqt-fg-muted)]";

const formatClock = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

const span = (from: number, to: number) => `${formatClock(from)}–${formatClock(to)}`;

type Item = { kind: "kill"; time: number; kill: TimelineKill } | { kind: "mark"; time: number; mark: TimelineMark };

/** A fight, or the kills that belong to no fight; `fight` is null for the latter (and for a feed of marks only). */
interface Group {
  key: string;
  fight: TimelineFight | null;
  /** A feed with no kill at all has nothing to head. */
  header: boolean;
  from: number;
  to: number;
  home: number | null;
  away: number | null;
  items: Item[];
}

interface RoundView {
  round: number;
  kills: TimelineKill[];
  ultStarts: TimelineMark[];
  fights: TimelineFight[];
  groups: Group[];
}

const blockId = (round: number, no: number | "outside") => `fight-${round}-${no}`;

/** Scroll a fight block into the modal body's view and flash it once. */
function bringIntoView(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
  if (reduced) return;
  el.animate(
    [{ backgroundColor: "color-mix(in srgb, var(--aqt-teal) 14%, transparent)" }, { backgroundColor: "transparent" }],
    { duration: 1200, easing: "ease-out" }
  );
}

/** A small score ("3 : 2", "1 – 5"): tabular, with room around the separator. */
function Pair({
  home,
  away,
  sep,
  homeClass,
  awayClass
}: Readonly<{
  home: number | string;
  away: number | string;
  sep: string;
  homeClass?: string;
  awayClass?: string;
}>) {
  return (
    <span className="aqt-tnum inline-flex items-baseline gap-[0.35em] whitespace-nowrap">
      <span className={cn("min-w-[1ch] text-center", homeClass)}>{home}</span>
      <span className={FAINT_TEXT}>{sep}</span>
      <span className={cn("min-w-[1ch] text-center", awayClass)}>{away}</span>
    </span>
  );
}

function LegendItem({ swatch, children }: Readonly<{ swatch: ReactNode; children: ReactNode }>) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
        {swatch}
      </svg>
      {children}
    </span>
  );
}

const W = 1000;
const H = 92;
const PAD = 16;
const MID = 44;

const KillFeedTimeline = ({ matchId, members, home, away, round, focus }: KillFeedTimelineProps) => {
  const t = useTranslations();
  const { status, refetch, timeline } = useMatchTimeline(matchId);

  const nameByMemberId = useMemo(
    () => new Map(members.map((member) => [member.workspace_member_id, splitHandle(member.handle_snapshot).name])),
    [members]
  );
  const nameOf = (memberId: number | null) => (memberId == null ? "—" : (nameByMemberId.get(memberId) ?? "—"));
  /** Events name `encounter_team_id`s; the duel's two participations are the only sides there are. */
  const sideOf = (teamId: number | null): TimelineSide | null =>
    teamId === home.id ? "home" : teamId === away.id ? "away" : null;

  const rounds = useMemo<RoundView[]>(() => {
    if (!timeline) return [];
    const inScope = (segment: number) => round === 0 || timelineRound(segment) === round;
    const kills = timeline.kills.filter((kill) => inScope(kill.round));
    const marks = timeline.marks.filter((mark) => inScope(mark.round));
    const fights = readFights(kills, home.id, away.id);
    const side = (teamId: number | null): TimelineSide | null =>
      teamId === home.id ? "home" : teamId === away.id ? "away" : null;
    const numbers = [...new Set([...kills, ...marks].map((row) => timelineRound(row.round)))].sort((a, b) => a - b);

    return numbers.map((no) => {
      const roundKills = kills.filter((kill) => timelineRound(kill.round) === no);
      const roundFights = fights.filter((fight) => fight.round === no);
      const roundMarks = marks.filter((mark) => timelineRound(mark.round) === no);

      // Fights and loose kills in the order they began; neighbouring loose kills are one group.
      const units = [
        ...roundFights.map((fight) => ({ fight, kills: [...fight.kills], from: fight.from })),
        ...roundKills
          .filter((kill) => kill.fight == null)
          .map((kill) => ({ fight: null as TimelineFight | null, kills: [kill], from: kill.time }))
      ].sort((a, b) => a.from - b.from);
      const merged: typeof units = [];
      for (const unit of units) {
        const last = merged[merged.length - 1];
        if (!unit.fight && last && !last.fight) last.kills.push(...unit.kills);
        else merged.push(unit);
      }

      const groups: Group[] = merged.map((unit, index) => {
        const sides = unit.kills.map((kill) => side(kill.killer_team_id));
        const known = sides.every((s) => s != null);
        return {
          key: unit.fight ? blockId(no, unit.fight.no) : `${blockId(no, "outside")}-${index}`,
          fight: unit.fight,
          header: true,
          from: unit.fight ? unit.fight.from : Math.min(...unit.kills.map((kill) => kill.time)),
          to: unit.fight ? unit.fight.to : Math.max(...unit.kills.map((kill) => kill.time)),
          home: unit.fight ? unit.fight.home : known ? sides.filter((s) => s === "home").length : null,
          away: unit.fight ? unit.fight.away : known ? sides.filter((s) => s === "away").length : null,
          items: unit.kills.map((kill) => ({ kind: "kill", time: kill.time, kill }))
        };
      });
      if (groups.length === 0) {
        groups.push({ key: blockId(no, "outside"), fight: null, header: false, from: 0, to: 0, home: null, away: null, items: [] });
      }
      // A mark belongs to the group in progress: the latest one that began by then (the first, before any).
      for (const mark of roundMarks) {
        let index = 0;
        groups.forEach((group, i) => {
          if (group.header && group.from <= mark.time) index = i;
        });
        groups[index].items.push({ kind: "mark", time: mark.time, mark });
      }
      for (const group of groups) group.items.sort((a, b) => a.time - b.time);

      return {
        round: no,
        kills: roundKills,
        ultStarts: roundMarks.filter((mark) => mark.name === "ultimate_start"),
        fights: roundFights,
        groups
      };
    });
  }, [timeline, round, home.id, away.id]);

  // Jump to the requested fight once its block is on screen (the data may still be loading when the request lands).
  const handled = useRef<number | null>(null);
  const ready = status === "success";
  useEffect(() => {
    if (!focus || !ready || handled.current === focus.nonce) return;
    handled.current = focus.nonce;
    bringIntoView(blockId(focus.round, focus.fight));
  }, [focus, ready]);

  const tally = (teamIds: (number | null)[], side: TimelineSide) => teamIds.filter((id) => sideOf(id) === side).length;
  const count = (kills: readonly TimelineKill[], side: TimelineSide) =>
    tally(kills.map((kill) => kill.killer_team_id), side);

  if (status === "pending") {
    return (
      <div role="status" className="flex flex-col gap-2">
        <span className="sr-only">{t("matches.timeline.loading")}</span>
        {[0, 1, 2, 3, 4, 5].map((row) => (
          <Skeleton key={row} aria-hidden className="h-[30px] w-full" />
        ))}
      </div>
    );
  }
  if (status === "error") {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 py-8 text-center">
        <p className="text-caption text-[color:var(--aqt-rose)]">{t("matches.timeline.error")}</p>
        <Button variant="outline" size="sm" onClick={() => void refetch()}>
          <RotateCw aria-hidden="true" />
          {t("common.retry")}
        </Button>
      </div>
    );
  }
  if (rounds.length === 0) {
    return <p className="py-8 text-center text-caption text-[color:var(--aqt-fg-dim)]">{t("matches.timeline.empty")}</p>;
  }

  const allKills = rounds.flatMap((view) => view.kills);
  const ultTeams = rounds.flatMap((view) => view.ultStarts.map((mark) => mark.team_id));
  const fightCount = rounds.reduce((total, view) => total + view.fights.length, 0);

  const legend = (
    <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5 text-label text-[color:var(--aqt-fg-dim)]">
      <LegendItem swatch={<circle cx="7" cy="7" r="4" fill={SEAT_FILL.home} />}>
        {t("matches.timeline.legendKills", { team: home.name })}
      </LegendItem>
      <LegendItem swatch={<circle cx="7" cy="7" r="4" fill={SEAT_FILL.away} />}>
        {t("matches.timeline.legendKills", { team: away.name })}
      </LegendItem>
      <LegendItem
        swatch={<circle cx="7" cy="7" r="4" fill="var(--aqt-fg-faint)" stroke="var(--aqt-violet)" strokeWidth="2" />}
      >
        {t("matches.timeline.ultKill")}
      </LegendItem>
      <LegendItem swatch={<rect x="6" y="2" width="2" height="10" rx="1" fill="var(--aqt-violet)" />}>
        {t("matches.timeline.ultStart")}
      </LegendItem>
      <LegendItem swatch={<rect x="1" y="2" width="12" height="10" rx="3" fill="var(--aqt-overlay-4)" />}>
        {t("matches.timeline.legendFight")}
      </LegendItem>
    </div>
  );

  const chart = (view: RoundView) => {
    const times = [...view.kills, ...view.ultStarts].map((row) => row.time);
    const t0 = Math.max(0, Math.min(...times) - 8);
    const t1 = Math.max(...times) + 8;
    const x = (time: number) => PAD + ((time - t0) / (t1 - t0)) * (W - 2 * PAD);
    const ticks: number[] = [];
    for (let s = Math.ceil(t0 / 60) * 60; s <= t1; s += 60) ticks.push(s);
    const label = (fight: TimelineFight) =>
      `${t("matches.timeline.fight", { n: fight.no })} · ${span(fight.from, fight.to)} · ${fight.home ?? "—"}–${fight.away ?? "—"}`;
    const bandX = (fight: TimelineFight) => x(fight.from) - 6;
    const bandW = (fight: TimelineFight) => Math.max(12, x(fight.to) - x(fight.from) + 12);
    const pct = (value: number, of: number) => `${(value / of) * 100}%`;
    return (
      <div className="overflow-x-auto">
        {/* The bands are drawn in the SVG and pressed through real buttons laid over them, at the same
            proportions as the viewBox, so a fight is a focusable control and the chart stays an image. */}
        <div className="relative min-w-[640px] rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)]">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            aria-label={t("matches.timeline.roundAria", {
              round: view.round,
              home: count(view.kills, "home"),
              away: count(view.kills, "away")
            })}
            className="block h-auto w-full"
          >
            {view.fights.map((fight) => (
              <g key={fight.id}>
                <rect
                  x={bandX(fight)}
                  y={12}
                  width={bandW(fight)}
                  height={MID * 2 - 24}
                  rx={6}
                  className="fill-[color:var(--aqt-overlay-3)]"
                />
                <text
                  x={x(fight.from) - 4}
                  y={10}
                  className="pointer-events-none fill-[color:var(--aqt-fg-dim)] text-label font-medium"
                >
                  {fight.no}
                </text>
              </g>
            ))}
          <line x1={PAD} x2={W - PAD} y1={MID} y2={MID} stroke="var(--aqt-border-2)" />
          {view.ultStarts.map((mark, index) => (
            <rect
              key={`u-${index}`}
              x={x(mark.time) - 1}
              y={sideOf(mark.team_id) === "home" ? MID - 9 : MID + 1}
              width={2}
              height={8}
              rx={1}
              fill="var(--aqt-violet)"
              opacity={0.8}
            >
              <title>{`${formatClock(mark.time)} ${nameOf(mark.member_id)}: ${t("matches.timeline.ultStart")}`}</title>
            </rect>
          ))}
          {view.kills.map((kill, index) => {
            const killerSide = sideOf(kill.killer_team_id);
            return (
              <circle
                key={`k-${index}`}
                cx={x(kill.time)}
                cy={killerSide === "home" ? MID - 18 : MID + 18}
                r={4.5}
                fill={killerSide ? SEAT_FILL[killerSide] : "var(--aqt-fg-faint)"}
                stroke={kill.ability === "Ultimate" ? "var(--aqt-violet)" : undefined}
                strokeWidth={kill.ability === "Ultimate" ? 2.5 : undefined}
              >
                <title>{`${formatClock(kill.time)} ${nameOf(kill.killer_member_id)} → ${nameOf(kill.victim_member_id)}`}</title>
              </circle>
            );
          })}
          {ticks.map((s) => (
            <text
              key={s}
              x={x(s)}
              y={H - 4}
              textAnchor="middle"
              className="fill-[color:var(--aqt-fg-faint)] text-label font-medium"
            >
              {formatClock(s)}
            </text>
          ))}
          </svg>
          {view.fights.map((fight) => (
            <Button
              key={fight.id}
              type="button"
              variant="ghost"
              aria-label={label(fight)}
              title={label(fight)}
              onClick={() => bringIntoView(blockId(view.round, fight.no))}
              className="absolute h-auto min-h-0 rounded-md p-0"
              style={{
                left: pct(bandX(fight), W),
                width: pct(bandW(fight), W),
                top: pct(12, H),
                height: pct(MID * 2 - 24, H)
              }}
            />
          ))}
        </div>
      </div>
    );
  };

  const killRow = (kill: TimelineKill, key: string) => {
    const killerSide = sideOf(kill.killer_team_id);
    const ult = kill.ability === "Ultimate";
    return (
      <div
        key={key}
        className={cn(
          "grid h-[30px] grid-cols-[38px_minmax(0,1fr)_18px_minmax(0,1fr)_36px] items-center gap-2 rounded-md px-1.5 hover:bg-[color:var(--aqt-overlay-2)]",
          ult && "bg-[color:color-mix(in_srgb,var(--aqt-violet)_8%,transparent)]"
        )}
      >
        <span className={cn("aqt-tnum text-label", FAINT_TEXT)}>{formatClock(kill.time)}</span>
        <span className="flex min-w-0 items-center gap-2">
          {kill.killer_entity ? <CatalogEntityImage entity={kill.killer_entity} size={22} /> : null}
          <span
            className={cn("truncate text-caption font-semibold", killerSide ? SEAT_TEXT[killerSide] : MUTED_TEXT)}
          >
            {nameOf(kill.killer_member_id)}
          </span>
        </span>
        {ult ? (
          <span
            role="img"
            aria-label={t("matches.timeline.ultKill")}
            title={t("matches.timeline.ultKill")}
            className="grid text-[color:var(--aqt-violet)]"
          >
            <Zap className="size-4" aria-hidden="true" />
          </span>
        ) : (
          <ArrowRight className={cn("size-4", FAINT_TEXT)} aria-hidden="true" />
        )}
        <span className="flex min-w-0 items-center gap-2">
          {kill.victim_entity ? (
            <span className="opacity-70">
              <CatalogEntityImage entity={kill.victim_entity} size={22} />
            </span>
          ) : null}
          <span className={cn("truncate text-caption", MUTED_TEXT)}>{nameOf(kill.victim_member_id)}</span>
        </span>
        <span className="flex items-center justify-end gap-1">
          {kill.is_critical_hit ? (
            <span
              role="img"
              aria-label={t("matches.timeline.critical")}
              title={t("matches.timeline.critical")}
              className="grid text-[color:var(--aqt-amber)]"
            >
              <Crosshair className="size-4" aria-hidden="true" />
            </span>
          ) : null}
          {kill.is_environmental ? (
            <span
              role="img"
              aria-label={t("matches.timeline.environmental")}
              title={t("matches.timeline.environmental")}
              className={cn("grid", MUTED_TEXT)}
            >
              <Skull className="size-4" aria-hidden="true" />
            </span>
          ) : null}
        </span>
      </div>
    );
  };

  const markRow = (mark: TimelineMark, key: string) => {
    const markSide = sideOf(mark.team_id);
    const rez = mark.name === "mercy_rez";
    const ultEnd = mark.name === "ultimate_end";
    const Icon = rez ? Plus : ultEnd ? ZapOff : Zap;
    const label = rez
      ? t("matches.timeline.resurrect")
      : ultEnd
        ? t("matches.timeline.ultEnd")
        : t("matches.timeline.ultStart");
    return (
      <div key={key} className="flex h-6 items-center gap-2 px-1.5">
        <span className={cn("aqt-tnum w-[38px] shrink-0 text-label", FAINT_TEXT)}>{formatClock(mark.time)}</span>
        <Icon
          className={cn(
            "size-3.5 shrink-0",
            rez ? "text-[color:var(--aqt-support)]" : "text-[color:var(--aqt-violet)]",
            ultEnd && "opacity-60"
          )}
          aria-hidden="true"
        />
        {mark.entity ? (
          <span className="opacity-80">
            <CatalogEntityImage entity={mark.entity} size={18} />
          </span>
        ) : null}
        <span className={cn("truncate text-label font-medium", markSide ? SEAT_TEXT[markSide] : MUTED_TEXT)}>
          {nameOf(mark.member_id)}
        </span>
        <Eyebrow tone="dim">{label}</Eyebrow>
        {rez && mark.related_member_id != null ? (
          <span className={cn("flex min-w-0 items-center gap-1 text-label", FAINT_TEXT)}>
            <ArrowRight className="size-3 shrink-0" aria-hidden="true" />
            <span className="truncate">{nameOf(mark.related_member_id)}</span>
          </span>
        ) : null}
      </div>
    );
  };

  const groupBlock = (group: Group) => {
    const tied = group.home === group.away;
    return (
      <div key={group.key} id={group.key} className="break-inside-avoid rounded-lg pb-3.5">
        {group.header ? (
          <div className="flex h-7 items-center gap-2 px-1.5">
            <Eyebrow className="aqt-tnum">
              {group.fight ? t("matches.timeline.fight", { n: group.fight.no }) : t("matches.timeline.outside")}
            </Eyebrow>
            {group.fight ? (
              <span className={cn("aqt-tnum text-label", FAINT_TEXT)}>{span(group.from, group.to)}</span>
            ) : null}
            <Separator className="flex-1" />
            <span className="text-caption font-semibold">
              {group.home == null || group.away == null ? (
                <span className={FAINT_TEXT}>—</span>
              ) : (
                <Pair
                  home={group.home}
                  away={group.away}
                  sep="–"
                  homeClass={!tied && group.home > group.away ? SEAT_TEXT.home : FAINT_TEXT}
                  awayClass={!tied && group.away > group.home ? SEAT_TEXT.away : FAINT_TEXT}
                />
              )}
            </span>
          </div>
        ) : null}
        {group.items.map((item, index) =>
          item.kind === "kill"
            ? killRow(item.kill, `${group.key}-k${index}`)
            : markRow(item.mark, `${group.key}-m${index}`)
        )}
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap gap-x-5 gap-y-1.5 text-caption text-[color:var(--aqt-fg-dim)]">
        <span className="inline-flex items-baseline gap-1.5">
          {t("matches.timeline.finalBlows")}
          <span className="font-semibold text-[color:var(--aqt-fg)]">
            <Pair home={count(allKills, "home")} away={count(allKills, "away")} sep=":" />
          </span>
        </span>
        <span className="inline-flex items-baseline gap-1.5">
          {t("matches.timeline.fights")}
          <span className="aqt-tnum font-semibold text-[color:var(--aqt-fg)]">{fightCount}</span>
        </span>
        <span className="inline-flex items-baseline gap-1.5">
          {t("matches.timeline.ults")}
          <span className="font-semibold text-[color:var(--aqt-fg)]">
            <Pair home={tally(ultTeams, "home")} away={tally(ultTeams, "away")} sep=":" />
          </span>
        </span>
      </div>

      {rounds.map((view, index) => (
        <section key={view.round} aria-label={t("matches.round", { round: view.round })} className="flex flex-col">
          {rounds.length > 1 ? (
            <div className="mb-2 flex items-center gap-3">
              <Eyebrow>{t("matches.round", { round: view.round })}</Eyebrow>
              <span className="ms-auto text-caption font-semibold">
                <Pair
                  home={count(view.kills, "home")}
                  away={count(view.kills, "away")}
                  sep=":"
                  homeClass={SEAT_TEXT.home}
                  awayClass={SEAT_TEXT.away}
                />
              </span>
            </div>
          ) : null}
          {view.kills.length > 0 ? chart(view) : null}
          {index === 0 && view.kills.length > 0 ? legend : null}
          <div className="mt-4 lg:columns-2 lg:gap-8">{view.groups.map(groupBlock)}</div>
        </section>
      ))}
    </div>
  );
};

export default KillFeedTimeline;
