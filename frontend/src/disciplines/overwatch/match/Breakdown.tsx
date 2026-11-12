"use client";

import { useId, useMemo, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Repeat } from "lucide-react";
import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import PlayerName from "@/components/PlayerName";
import { LoadErrorNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import Image from "@/components/ui/image";
import { Skeleton } from "@/components/ui/skeleton";
import { useHeroClass } from "@/disciplines/overwatch/character/classes";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { DisciplineMetadata } from "@/types/discipline.types";
import type { MatchWithStats } from "@/types/encounter.types";
import { LogStatsName } from "../stat-names";
import {
  CARRY_STATS,
  sideOfTeam,
  TOTAL_STATS,
  betterSide,
  bestRuns,
  carryMix,
  carryShares,
  duelOf,
  findMvp,
  leadingSide,
  lineupColumns,
  lineupRow,
  mvpFigures,
  readFlow,
  roleDuels,
  shareLabel,
  summarizeFights,
  type Duel,
  type Flow,
  type RoleDuels
} from "./breakdown.model";
import type { FightRef } from "./MatchStats";
import {
  STAT_META,
  activePlayers,
  availableRounds,
  compareByClass,
  formatStat,
  playerClass,
  playerStat,
  teamTotal,
  type MatchStatsPlayer
} from "./stats";
import { readFights, timelineRound, type TimelineSide } from "./timeline";
import { useMatchTimeline } from "./useMatchTimeline";
import { HERO_PLAYED_SECONDS, type OwTeam } from "./view";

interface BreakdownProps {
  match: MatchWithStats;
  home: OwTeam;
  away: OwTeam;
  /** 0 = the whole map, else one round. */
  round: number;
  metadata: DisciplineMetadata;
  onGotoFight: (fight: FightRef) => void;
}

type Side = TimelineSide;
/** next-intl's `t`, taken for keys only known at run time. */
type Translator = (key: never) => string;

const SEAT: Record<Side, string> = { home: "var(--aqt-teal)", away: "var(--aqt-rose)" };
const FAINT = "text-[color:var(--aqt-fg-faint)]";
const DIM = "text-[color:var(--aqt-fg-dim)]";
const MUTED = "text-[color:var(--aqt-fg-muted)]";
const HAIRLINE = "border-[color:var(--aqt-border)]";

const formatClock = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

const signed = (value: number) => (value > 0 ? `+${value}` : value < 0 ? `\u2212${-value}` : "0");

const statLabel = (t: Translator, name: LogStatsName) => t((STAT_META[name]?.labelKey ?? name) as never);

/** What `useHeroClass` hands out, as far as this tab uses it. */
interface HeroClassView {
  label: (cls: string | null | undefined) => string;
  color: (cls: string | null | undefined) => string;
  icon: (cls: string | null | undefined, size: number) => ReactNode;
}

/** A player's name in this game, linked to his profile through `display.canonical`; sized by its parent. */
function PlayerLabel({ player, tag }: Readonly<{ player: MatchStatsPlayer; tag?: "muted" | "hidden" }>) {
  return <PlayerName display={player.display} tag={tag} className="text-[length:inherit]" />;
}

/** `h : a`, the side with less dimmed. */
function PairScore({
  home,
  away,
  winner,
  loseClass = DIM,
  className
}: Readonly<{ home: ReactNode; away: ReactNode; winner: Side | null; loseClass?: string; className?: string }>) {
  return (
    <span className={cn("aqt-tnum inline-flex items-baseline gap-[0.4em] whitespace-nowrap", className)}>
      <span className={cn(winner === "away" && loseClass)}>{home}</span>
      <span className={FAINT}>:</span>
      <span className={cn(winner === "home" && loseClass)}>{away}</span>
    </span>
  );
}

function SeatBar({ side }: Readonly<{ side: Side }>) {
  return <span aria-hidden className="h-3.5 w-[3px] flex-none rounded-sm" style={{ background: SEAT[side] }} />;
}

function Section({ title, hint, children }: Readonly<{ title: string; hint?: string; children: ReactNode }>) {
  const id = useId();
  return (
    <section aria-labelledby={id}>
      <div className="mb-3 flex min-h-7 flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <h3 id={id} className="text-ui font-semibold">
          {title}
        </h3>
        {hint ? <span className={cn("text-caption", FAINT)}>{hint}</span> : null}
      </div>
      {children}
    </section>
  );
}

/** The hero a player is drawn with: the longest of the round, else of the whole map. */
const mainHero = (player: MatchStatsPlayer, round: number) =>
  (player.heroTimes[round]?.length ? player.heroTimes[round] : player.heroTimes[0])?.[0]?.entity ?? null;

// ── Player of the map ────────────────────────────────────────────────────────

function MvpCard({
  home,
  away,
  round,
  roles,
  heroClass
}: Readonly<{
  home: OwTeam;
  away: OwTeam;
  round: number;
  roles: RoleDuels[];
  heroClass: HeroClassView;
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const mvp = findMvp(home, away, round);
  if (!mvp) return null;
  const { player, side, rival } = mvp;
  const team = side === "home" ? home : away;
  const rivalSide: Side = side === "home" ? "away" : "home";
  const cls = playerClass(player, round);
  const main = mainHero(player, round);
  const played = (player.heroTimes[round]?.length ? player.heroTimes[round] : player.heroTimes[0] ?? []).filter(
    (hero) => hero.seconds >= HERO_PLAYED_SECONDS
  );
  const figures = [...mvpFigures(player, round), LogStatsName.Deaths];
  const duel = duelOf(roles, player);
  const scope = round === 0 ? t("matches.breakdown.playerOfMap") : t("matches.breakdown.playerOfRound", { round });
  const portrait = "size-[72px] flex-none rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)] sm:size-28";

  return (
    <Card asChild className="relative isolate grid grid-cols-[72px_minmax(0,1fr)] gap-x-4 overflow-hidden p-4 sm:grid-cols-[112px_minmax(0,1fr)]">
      <article aria-label={`${scope}: ${player.display.name}`}>
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 -z-10"
          style={{
            background: `radial-gradient(110% 100% at 0% 0%, color-mix(in srgb, ${SEAT[side]} 15%, transparent), transparent 62%)`
          }}
        />
        {main?.image_path ? (
          <Image src={main.image_path} alt="" width={112} height={112} title={main.name} className={cn(portrait, "object-cover")} />
        ) : (
          <span className={portrait} />
        )}
        <div className="min-w-0">
          <Eyebrow title={t("matches.breakdown.impactFirst")}>{scope}</Eyebrow>
          <div className="my-1.5 flex items-baseline gap-1 font-display text-heading font-semibold sm:text-title">
            <PlayerLabel player={player} />
          </div>
          <div className={cn("flex flex-wrap items-center gap-x-2 gap-y-0.5 text-caption", DIM)}>
            {cls ? (
              <>
                <span className="inline-flex items-center gap-1" style={{ color: heroClass.color(cls) }}>
                  {heroClass.icon(cls, 14)}
                  {heroClass.label(cls)}
                </span>
                <span aria-hidden>·</span>
              </>
            ) : null}
            <span className="inline-flex items-center gap-1.5">
              <SeatBar side={side} />
              {team.name}
            </span>
          </div>
          {played.length ? (
            <div className={cn("mt-1.5 truncate text-caption", DIM)}>
              {played.map((hero, index) => (
                <span key={hero.entity.id}>
                  {index ? " · " : null}
                  <b className={cn("font-medium", MUTED)}>{hero.entity.name}</b>{" "}
                  <span className="aqt-tnum">{formatClock(hero.seconds)}</span>
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <dl className="col-span-full mt-4 grid grid-cols-3 gap-3">
          {figures.map((name) => (
            <div key={name}>
              <Eyebrow as="dt">{statLabel(t, name)}</Eyebrow>
              <dd className="aqt-tnum m-0 mt-1 font-display text-heading font-semibold">
                {formatStat(name, playerStat(player, round, name), format)}
              </dd>
            </div>
          ))}
        </dl>
        <div className={cn("col-span-full mt-3.5 flex flex-wrap gap-x-4 gap-y-1 border-t pt-3 text-caption", HAIRLINE, DIM)}>
          {duel ? (
            <span>
              {t("matches.breakdown.duelWith", { name: duel.opponent.display.name })}{" "}
              <PairScore
                home={duel.mine}
                away={duel.theirs}
                winner={leadingSide(duel.mine, duel.theirs)}
                className="font-semibold text-[color:var(--aqt-fg)]"
              />
            </span>
          ) : null}
          {rival ? (
            <span>
              {t.rich("matches.breakdown.rivalBest", {
                name: rival.player.display.name,
                who: (chunks) => (
                  <span className="font-semibold" style={{ color: SEAT[rivalSide] }}>
                    {chunks}
                  </span>
                ),
                place: rival.place
              })}
            </span>
          ) : null}
        </div>
      </article>
    </Card>
  );
}

// ── Team totals ──────────────────────────────────────────────────────────────

function Totals({ home, away, round, withMvp }: Readonly<{ home: OwTeam; away: OwTeam; round: number; withMvp: boolean }>) {
  const t = useTranslations();
  const format = useFormatter();
  return (
    <Card asChild className="overflow-hidden bg-transparent">
      <dl
        aria-label={t("matches.breakdown.totals")}
        className={cn("m-0 grid grid-cols-2 sm:grid-cols-3", withMvp ? "lg:auto-rows-fr" : "lg:grid-cols-6")}
      >
        {TOTAL_STATS.map((name) => {
          const h = teamTotal(home, round, name);
          const a = teamTotal(away, round, name);
          const label = name === LogStatsName.UltimatesUsed ? t("matches.breakdown.ultimates") : statLabel(t, name);
          return (
            <div
              key={name}
              className={cn("-mb-px -me-px flex min-w-0 flex-col justify-center border-b border-e px-4 pb-3.5 pt-3", HAIRLINE)}
            >
              <Eyebrow as="dt" title={statLabel(t, name)}>
                {label}
              </Eyebrow>
              <dd className="m-0 mt-2 font-display text-heading font-semibold">
                <PairScore
                  home={formatStat(name, h, format)}
                  away={formatStat(name, a, format)}
                  winner={betterSide(name, h, a)}
                />
              </dd>
            </div>
          );
        })}
      </dl>
    </Card>
  );
}

// ── Map flow ─────────────────────────────────────────────────────────────────

const W = 1000;
const H = 230;
const PAD = { left: 44, right: 16, top: 22, bottom: 28 };

function FlowChart({
  flow,
  nameOf,
  ariaLabel
}: Readonly<{
  flow: Flow;
  nameOf: (memberId: number | null) => string;
  ariaLabel: string;
}>) {
  const t = useTranslations();
  const uid = useId().replace(/:/g, "");
  const { t0, t1, points, top, bottom, starts } = flow;
  const x = (time: number) => PAD.left + ((time - t0) / (t1 - t0)) * (W - PAD.left - PAD.right);
  const y = (value: number) => PAD.top + ((top - value) / (top + bottom)) * (H - PAD.top - PAD.bottom);
  const zero = y(0);
  let line = `M${x(t0)},${zero}`;
  for (const point of points) line += `H${x(point.time).toFixed(1)}V${y(point.diff).toFixed(1)}`;
  line += `H${x(t1)}`;
  const area = `${line}V${zero}Z`;
  const step = t1 - t0 > 480 ? 120 : 60;
  const ticks: number[] = [];
  for (let s = Math.ceil(t0 / step) * step; s <= t1; s += step) ticks.push(s);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={ariaLabel}
      className={cn("block h-auto w-full min-w-[520px] rounded-xl border bg-[color:var(--aqt-overlay-1)]", HAIRLINE)}
    >
      <defs>
        <clipPath id={`${uid}-up`}>
          <rect x={0} y={0} width={W} height={zero} />
        </clipPath>
        <clipPath id={`${uid}-dn`}>
          <rect x={0} y={zero} width={W} height={H - zero} />
        </clipPath>
      </defs>
      <path d={area} fill={SEAT.home} opacity={0.2} clipPath={`url(#${uid}-up)`} />
      <path d={area} fill={SEAT.away} opacity={0.2} clipPath={`url(#${uid}-dn)`} />
      {starts.map(({ round, time }) => (
        <g key={round}>
          <line
            x1={x(time)}
            x2={x(time)}
            y1={PAD.top - 8}
            y2={H - PAD.bottom}
            stroke="var(--aqt-border-3)"
            strokeDasharray="3 4"
          />
          <text x={x(time) + 6} y={PAD.top - 2} className="fill-[color:var(--aqt-fg-faint)] text-label font-medium">
            {t("matches.roundShort", { round })}
          </text>
        </g>
      ))}
      <line x1={PAD.left} x2={W - PAD.right} y1={zero} y2={zero} stroke="var(--aqt-border-3)" />
      <path d={line} fill="none" stroke="var(--aqt-fg-muted)" strokeWidth={1.5} strokeLinejoin="round" />
      <text x={PAD.left - 8} y={y(top) + 4} textAnchor="end" className="text-label font-medium" style={{ fill: SEAT.home }}>
        +{top}
      </text>
      <text x={PAD.left - 8} y={zero + 4} textAnchor="end" className="fill-[color:var(--aqt-fg-faint)] text-label font-medium">
        0
      </text>
      <text x={PAD.left - 8} y={y(-bottom) + 4} textAnchor="end" className="text-label font-medium" style={{ fill: SEAT.away }}>
        +{bottom}
      </text>
      {ticks.map((s) => (
        <text key={s} x={x(s)} y={H - 8} textAnchor="middle" className="fill-[color:var(--aqt-fg-faint)] text-label font-medium">
          {formatClock(s)}
        </text>
      ))}
      {points.map((point, index) => (
        <circle key={index} cx={x(point.time)} cy={y(point.diff)} r={4} className="fill-transparent hover:fill-[color:var(--aqt-fg)]">
          <title>{`${formatClock(point.time)} · ${nameOf(point.kill.killer_member_id)} → ${nameOf(point.kill.victim_member_id)} · ${signed(point.diff)}`}</title>
        </circle>
      ))}
    </svg>
  );
}

function FlowSkeleton() {
  return (
    <div aria-busy className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(260px,1fr)] lg:gap-x-7">
      <Skeleton className="aspect-[1000/230] min-h-40 w-full" />
      <div className="grid gap-3">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-10" />
        ))}
      </div>
    </div>
  );
}

// ── Lineups ──────────────────────────────────────────────────────────────────

function Lineup({
  team,
  side,
  round,
  columns,
  heroClass
}: Readonly<{
  team: OwTeam;
  side: Side;
  round: number;
  columns: number[];
  heroClass: HeroClassView;
}>) {
  const t = useTranslations();
  const players = activePlayers(team, round).sort(compareByClass(round));
  const label = (column: number) => (column === 0 ? t("matches.allMatch") : t("matches.round", { round: column }));
  const cell = "min-w-0 border-t py-2 pe-2.5";
  return (
    <div
      role="group"
      aria-label={team.name}
      className="grid items-center"
      style={{ gridTemplateColumns: `minmax(104px,140px) repeat(${columns.length},minmax(0,1fr))` }}
    >
      <div className="col-span-full flex min-w-0 items-center gap-2 pb-2.5 text-body font-semibold">
        <SeatBar side={side} />
        <span className="truncate" title={team.name}>
          {team.name}
        </span>
      </div>
      {columns.length > 1 ? (
        <>
          <div />
          {columns.map((column) => (
            <Eyebrow key={column} className="min-w-0 pe-2.5">
              {label(column)}
            </Eyebrow>
          ))}
        </>
      ) : null}
      {players.map((player) => {
        const cls = playerClass(player, round);
        return [
          <div key={`${player.workspace_member_id}-p`} className={cn(cell, HAIRLINE, "flex items-center gap-2 text-caption font-medium")}>
            {cls ? <span style={{ color: heroClass.color(cls) }}>{heroClass.icon(cls, 15)}</span> : null}
            <PlayerLabel player={player} tag="hidden" />
          </div>,
          ...lineupRow(player, columns).map((entry, index) => {
            const key = `${player.workspace_member_id}-${columns[index]}`;
            if (!entry) {
              return (
                <div key={key} className={cn(cell, HAIRLINE, "text-caption", FAINT)}>
                  {"\u2014"}
                </div>
              );
            }
            const { main, extras, all, swappedFrom } = entry;
            const swapText = swappedFrom
              ? t("matches.breakdown.swap", { from: swappedFrom.name, to: main.entity.name })
              : null;
            const listing = all.map((hero) => `${hero.entity.name} ${formatClock(hero.seconds)}`).join(", ");
            return (
              <div key={key} className={cn(cell, HAIRLINE, "flex items-center gap-2")} title={swapText ?? listing}>
                <CatalogEntityImage
                  entity={main.entity}
                  size={32}
                  rounded="lg"
                  decorative
                  className={cn(
                    swappedFrom && "outline outline-2 outline-offset-2 outline-[color:var(--aqt-teal)]"
                  )}
                />
                <div className="grid min-w-0">
                  <span
                    className={cn(
                      "hidden min-w-0 items-center gap-1 text-caption sm:flex",
                      swappedFrom ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg)]"
                    )}
                  >
                    {swappedFrom ? (
                      <span title={swapText ?? undefined} className="grid">
                        <Repeat className="size-3" aria-hidden />
                      </span>
                    ) : null}
                    <span className="truncate">{main.entity.name}</span>
                  </span>
                  <span className={cn("aqt-tnum flex items-center gap-1 text-label", FAINT)}>
                    {formatClock(main.seconds)}
                    {extras.map((entity) => (
                      <CatalogEntityImage key={entity.id} entity={entity} size={16} rounded="lg" decorative className="opacity-85" />
                    ))}
                  </span>
                </div>
              </div>
            );
          })
        ];
      })}
    </div>
  );
}

// ── Role duels ───────────────────────────────────────────────────────────────

function HalfBar({ pct, side, lose }: Readonly<{ pct: number; side: Side; lose: boolean }>) {
  return (
    <span className={cn("flex h-1.5 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)]", side === "home" && "justify-end")}>
      <span
        className="block h-full rounded-full"
        style={{ width: `${pct}%`, background: SEAT[side], opacity: lose ? 0.35 : 1 }}
      />
    </span>
  );
}

function DuelPerson({
  player,
  side,
  won,
  round
}: Readonly<{ player: MatchStatsPlayer | null; side: Side; won: boolean; round: number }>) {
  const placement = cn(
    "flex min-w-0 items-center gap-2 text-body",
    side === "away" && "col-start-2 row-start-1 justify-end text-end sm:col-auto sm:row-auto"
  );
  if (!player) return <div className={cn(placement, FAINT)}>{"\u2014"}</div>;
  const entity = player.heroes[round]?.[0] ?? mainHero(player, round);
  const image = <CatalogEntityImage entity={entity} size={28} rounded="lg" decorative />;
  return (
    <div className={cn(placement, won ? "font-semibold text-[color:var(--aqt-fg)]" : cn("font-medium", MUTED))}>
      {side === "home" ? image : null}
      <PlayerLabel player={player} tag="hidden" />
      {side === "away" ? image : null}
    </div>
  );
}

function DuelRow({ duel, round }: Readonly<{ duel: Duel; round: number }>) {
  const t = useTranslations();
  const format = useFormatter();
  const who = (player: MatchStatsPlayer | null) => (player ? player.display.name : "\u2014");
  return (
    <div className={cn("grid grid-cols-2 items-center gap-x-4 gap-y-2.5 border-t py-2.5 sm:grid-cols-[minmax(140px,190px)_repeat(3,minmax(0,1fr))_minmax(140px,190px)] sm:gap-x-6", HAIRLINE)}>
      <DuelPerson player={duel.home} side="home" won={duel.wins.home > duel.wins.away} round={round} />
      {duel.stats.map((stat) => {
        const max = Math.max(stat.home, stat.away, 1);
        const label = statLabel(t, stat.name);
        const h = formatStat(stat.name, stat.home, format);
        const a = formatStat(stat.name, stat.away, format);
        return (
          <div key={stat.name} className="col-span-full grid min-w-0 gap-1 sm:col-auto">
            <Eyebrow className="text-center">{label}</Eyebrow>
            <div
              role="img"
              aria-label={`${label}: ${who(duel.home)} ${h}, ${who(duel.away)} ${a}`}
              className="grid grid-cols-[56px_minmax(0,1fr)_minmax(0,1fr)_56px] items-center gap-1.5"
            >
              <span className={cn("aqt-tnum whitespace-nowrap text-end text-caption", stat.winner === "home" ? "font-bold text-[color:var(--aqt-fg)]" : MUTED)}>
                {duel.home ? h : ""}
              </span>
              <HalfBar pct={(stat.home / max) * 100} side="home" lose={stat.winner === "away"} />
              <HalfBar pct={(stat.away / max) * 100} side="away" lose={stat.winner === "home"} />
              <span className={cn("aqt-tnum whitespace-nowrap text-caption", stat.winner === "away" ? "font-bold text-[color:var(--aqt-fg)]" : MUTED)}>
                {duel.away ? a : ""}
              </span>
            </div>
          </div>
        );
      })}
      <DuelPerson player={duel.away} side="away" won={duel.wins.away > duel.wins.home} round={round} />
    </div>
  );
}

// ── Who carried ──────────────────────────────────────────────────────────────

function CarryRow({
  team,
  side,
  round,
  name
}: Readonly<{ team: OwTeam; side: Side; round: number; name: LogStatsName }>) {
  const t = useTranslations();
  const format = useFormatter();
  const { shares, total } = carryShares(team, round, name);
  const pct = (share: number) => Math.round(share * 100);
  const nameOf = (player: MatchStatsPlayer) => player.display.name;
  const summary = shares.map(({ player, share }) => `${nameOf(player)} ${pct(share)}%`);
  return (
    <div
      role="img"
      aria-label={`${team.name}, ${statLabel(t, name)}: ${summary.join(", ") || t("matches.breakdown.noData")}`}
      className="grid min-h-8 grid-cols-[3px_minmax(0,1fr)_64px] items-center gap-x-2.5 gap-y-0.5"
    >
      <SeatBar side={side} />
      {total > 0 ? (
        <div className="flex h-6 min-w-0 gap-0.5">
          {shares.map(({ player, value, share }, index) => {
            const mix = carryMix(index);
            const label = shareLabel(share);
            return (
              <span
                key={player.workspace_member_id}
                title={`${nameOf(player)}: ${formatStat(name, value, format)} · ${pct(share)}%`}
                className="block min-w-0 overflow-hidden whitespace-nowrap rounded-sm px-2 text-label font-semibold leading-6"
                style={{
                  width: `${share * 100}%`,
                  background: `color-mix(in srgb, ${SEAT[side]} ${mix}%, var(--aqt-card))`,
                  color: mix >= 70 ? "var(--aqt-bg)" : "var(--aqt-fg)"
                }}
              >
                {label === "full" ? <span className="hidden sm:inline">{`${nameOf(player)}\u00a0`}</span> : null}
                {label === "none" ? null : `${pct(share)}%`}
              </span>
            );
          })}
        </div>
      ) : (
        <span className={cn("text-caption", DIM)}>{t("matches.breakdown.noData")}</span>
      )}
      <span className={cn("aqt-tnum text-end text-caption", MUTED)}>{formatStat(name, total, format)}</span>
      {total > 0 ? (
        <span className={cn("col-start-2 mb-1.5 truncate text-label sm:hidden", DIM)}>
          {summary.slice(0, 2).join(" · ")}
        </span>
      ) : null}
    </div>
  );
}

// ── The tab ──────────────────────────────────────────────────────────────────

export default function Breakdown({ match, home, away, round, metadata, onGotoFight }: Readonly<BreakdownProps>) {
  const t = useTranslations();
  const format = useFormatter();
  const heroClass = useHeroClass(metadata);
  const { status, refetch, timeline } = useMatchTimeline(match.id);

  const flowData = useMemo(() => {
    if (!timeline) return null;
    const inView = (segment: number) => round === 0 || timelineRound(segment) === round;
    const kills = timeline.kills.filter((kill) => inView(kill.round));
    const flow = readFlow(
      kills,
      timeline.marks.filter((mark) => inView(mark.round)),
      home.id,
      away.id
    );
    const fights = readFights(timeline.kills, home.id, away.id).filter((fight) => inView(fight.round));
    const firstBlood = kills.length ? kills.reduce((first, kill) => (kill.time < first.time ? kill : first)) : null;
    return { kills, flow, fights, summary: summarizeFights(fights), runs: bestRuns(kills, home.id, away.id), firstBlood };
  }, [timeline, round, home.id, away.id]);

  const members = useMemo(() => {
    const map = new Map<number, { name: string; side: Side }>();
    for (const [team, side] of [[home, "home"], [away, "away"]] as const) {
      for (const player of team.players) map.set(player.workspace_member_id, { name: player.display.name, side });
    }
    return map;
  }, [home, away]);
  const nameOf = (memberId: number | null) => (memberId == null ? "\u2014" : (members.get(memberId)?.name ?? "\u2014"));

  const roles = roleDuels(home, away, round);
  const hasMvp = findMvp(home, away, round) != null;
  const columns = lineupColumns(availableRounds(home, away), round);
  const teams = [
    { team: home, side: "home" },
    { team: away, side: "away" }
  ] as const;

  const flow = flowData?.flow ?? null;
  const showFlow = status === "pending" || status === "error" || flow != null;
  const percent = (value: number | null) => (value == null ? "\u2014" : format.number(value / 100, { style: "percent" }));

  const flowBody = () => {
    if (status === "pending") return <FlowSkeleton />;
    if (status === "error") return <LoadErrorNote onRetry={() => void refetch()} />;
    if (!flowData || !flow) return null;
    const { summary, runs, firstBlood, fights } = flowData;
    const last = flow.points.at(-1)?.diff ?? 0;
    const ariaLabel = `${t("matches.breakdown.flowTitle")}: ${
      last === 0
        ? t("matches.breakdown.flowEven")
        : t("matches.breakdown.flowAria", { team: last > 0 ? home.name : away.name, lead: Math.abs(last) })
    }`;
    const biggest = summary.biggest;
    const row = "grid gap-1 border-t py-3 first:border-t-0 first:pt-0.5";
    const sub = cn("text-caption font-normal", DIM);
    return (
      <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(260px,1fr)] lg:gap-x-7">
        <div className="min-w-0 overflow-x-auto overscroll-x-contain [scrollbar-width:thin]">
          <FlowChart flow={flow} nameOf={nameOf} ariaLabel={ariaLabel} />
        </div>
        <dl className="m-0 min-w-0">
          {fights.length ? (
            <div className={cn(row, HAIRLINE)}>
              <Eyebrow as="dt">{t("matches.breakdown.fightsWon")}</Eyebrow>
              <dd className="m-0 text-body">
                <PairScore
                  home={summary.won.home}
                  away={summary.won.away}
                  winner={leadingSide(summary.won.home, summary.won.away)}
                  className="font-semibold"
                />
                {summary.draws ? <span className={sub}> · {t("matches.breakdown.draws", { count: summary.draws })}</span> : null}
              </dd>
            </div>
          ) : null}
          {fights.length ? (
            <div className={cn(row, HAIRLINE)}>
              <Eyebrow as="dt">{t("matches.breakdown.firstKill")}</Eyebrow>
              <dd className="m-0 text-body">
                <PairScore
                  home={summary.first.home}
                  away={summary.first.away}
                  winner={leadingSide(summary.first.home, summary.first.away)}
                  className="font-semibold"
                />
              </dd>
              <dd className={cn("m-0", sub)}>
                {t("matches.breakdown.conversion", {
                  home: percent(summary.conversion.home),
                  away: percent(summary.conversion.away)
                })}
              </dd>
            </div>
          ) : null}
          {firstBlood ? (
            <div className={cn(row, HAIRLINE)}>
              <Eyebrow as="dt">{t("matches.breakdown.firstBlood")}</Eyebrow>
              <dd className="m-0 text-body">
                <span className="aqt-tnum">{formatClock(firstBlood.time)}</span> ·{" "}
                <span
                  className="font-semibold"
                  style={{
                    color:
                      sideOfTeam(firstBlood.killer_team_id, home.id, away.id) === "home"
                        ? SEAT.home
                        : sideOfTeam(firstBlood.killer_team_id, home.id, away.id) === "away"
                          ? SEAT.away
                          : "var(--aqt-fg-muted)"
                  }}
                >
                  {nameOf(firstBlood.killer_member_id)}
                </span>{" "}
                → {nameOf(firstBlood.victim_member_id)}
              </dd>
            </div>
          ) : null}
          {biggest ? (
            <div className={cn(row, HAIRLINE)}>
              <Eyebrow as="dt">{t("matches.breakdown.biggestFight")}</Eyebrow>
              <dd className="m-0 text-body">
                <Button
                  variant="link"
                  size="inline"
                  onClick={() => onGotoFight({ round: biggest.round, fight: biggest.no })}
                >
                  {t("matches.timeline.fight", { n: biggest.no })}
                  {flow.starts.length ? ` · ${t("matches.roundShort", { round: biggest.round })}` : ""}
                </Button>{" "}
                · <span className="aqt-tnum">{formatClock(biggest.from)}</span> ·{" "}
                <PairScore
                  home={biggest.home}
                  away={biggest.away}
                  winner={biggest.winner}
                  className="font-semibold"
                />
              </dd>
            </div>
          ) : null}
          {runs.home || runs.away ? (
            <div className={cn(row, HAIRLINE)}>
              <Eyebrow as="dt">{t("matches.breakdown.streak")}</Eyebrow>
              {teams.map(({ team, side }) => {
                const run = runs[side];
                return run ? (
                  <dd key={side} className="m-0 text-body">
                    <span className="font-semibold" style={{ color: SEAT[side] }}>
                      {team.name}
                    </span>{" "}
                    · {t("matches.breakdown.inARow", { count: run.n })}
                    <span className={sub}>
                      {" "}
                      · <span className="aqt-tnum">{`${formatClock(run.from)}\u2013${formatClock(run.to)}`}</span>
                    </span>
                  </dd>
                ) : null;
              })}
            </div>
          ) : null}
        </dl>
      </div>
    );
  };

  return (
    <div className="grid gap-8">
      <div className={cn("grid gap-4", hasMvp && "lg:grid-cols-[minmax(380px,5fr)_minmax(0,7fr)]")}>
        <MvpCard home={home} away={away} round={round} roles={roles} heroClass={heroClass} />
        <Totals home={home} away={away} round={round} withMvp={hasMvp} />
      </div>

      {showFlow ? (
        <Section title={t("matches.breakdown.flowTitle")} hint={t("matches.breakdown.flowHint")}>
          {flowBody()}
        </Section>
      ) : null}

      <Section title={t("matches.breakdown.lineupsTitle")} hint={t("matches.breakdown.lineupsHint")}>
        <div className="grid gap-x-9 gap-y-6 lg:grid-cols-2">
          {teams.map(({ team, side }) => (
            <Lineup key={side} team={team} side={side} round={round} columns={columns} heroClass={heroClass} />
          ))}
        </div>
      </Section>

      {roles.length ? (
        <Section title={t("matches.breakdown.duelsTitle")} hint={t("matches.breakdown.duelsHint")}>
          {roles.map(({ role, duels, score }) => {
            const color = heroClass.color(role);
            return (
              <div key={role}>
                <div className="flex items-center gap-2 pb-1.5 pt-3.5 first:pt-0">
                  <span style={{ color }}>{heroClass.icon(role, 15)}</span>
                  <Eyebrow style={{ color }}>{heroClass.label(role)}</Eyebrow>
                  <PairScore
                    home={score.home}
                    away={score.away}
                    winner={leadingSide(score.home, score.away)}
                    loseClass={FAINT}
                    className="ms-auto text-caption font-semibold"
                  />
                </div>
                {duels.map((duel, index) => (
                  <DuelRow key={index} duel={duel} round={round} />
                ))}
              </div>
            );
          })}
        </Section>
      ) : null}

      <Section title={t("matches.breakdown.carryTitle")} hint={t("matches.breakdown.carryHint")}>
        <div className="grid gap-x-9 gap-y-5 lg:grid-cols-2">
          {CARRY_STATS.map((name) => (
            <div key={name}>
              <Eyebrow className="mb-2 block">{statLabel(t, name)}</Eyebrow>
              {teams.map(({ team, side }) => (
                <CarryRow key={side} team={team} side={side} round={round} name={name} />
              ))}
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}
