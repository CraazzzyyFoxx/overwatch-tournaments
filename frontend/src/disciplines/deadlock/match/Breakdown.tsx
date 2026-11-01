"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import { soulsSeries, teamSum, type DlPlayer, type DlTeam, type MatchFeed, type Side } from "./model";
import { DIM, FAINT, HAIRLINE, MUTED, PairScore, SEAT, SeatBar, Section, formatClock, leadingSide, useStatFormat } from "./parts";

const W = 1000;
const H = 240;
const PAD = { left: 56, right: 16, top: 18, bottom: 28 };

const tickStep = (seconds: number) => (seconds > 1800 ? 600 : 300);
const ticksOf = (t1: number) => {
  const step = tickStep(t1);
  const ticks: number[] = [];
  for (let s = step; s < t1; s += step) ticks.push(s);
  return ticks;
};

// ── Totals ───────────────────────────────────────────────────────────────────

/** The whole-match team figures the ribbon does not already carry (kills, souls and objectives live there). */
function Totals({ teams }: Readonly<{ teams: readonly [DlTeam, DlTeam] }>) {
  const t = useTranslations();
  const text = useStatFormat();
  const [home, away] = teams;
  const rows: { key: string; label: string; home: number | null; away: number | null; fewer?: boolean }[] = [
    { key: "damage", label: t("matches.deadlock.colTitle.player_damage"), home: teamSum(home, "player_damage"), away: teamSum(away, "player_damage") },
    { key: "obj", label: t("matches.deadlock.colTitle.boss_damage"), home: teamSum(home, "boss_damage"), away: teamSum(away, "boss_damage") },
    { key: "healing", label: t("matches.deadlock.colTitle.player_healing"), home: teamSum(home, "player_healing"), away: teamSum(away, "player_healing") },
    {
      key: "taken",
      label: t("matches.deadlock.colTitle.player_damage_taken"),
      home: teamSum(home, "player_damage_taken"),
      away: teamSum(away, "player_damage_taken"),
      fewer: true
    }
  ];
  return (
    <Card asChild className="overflow-hidden bg-transparent">
      <dl aria-label={t("matches.breakdown.totals")} className="m-0 grid grid-cols-2 lg:grid-cols-4">
        {rows.map((row) => (
          <div key={row.key} className={cn("-mb-px -me-px flex min-w-0 flex-col justify-center border-b border-e px-4 pb-3.5 pt-3", HAIRLINE)}>
            <Eyebrow as="dt" title={row.label} className="truncate">
              {row.label}
            </Eyebrow>
            <dd className="m-0 mt-2 font-display text-ui font-semibold sm:text-heading">
              {row.home === null || row.away === null ? (
                <Skeleton variant="text" className="w-20" />
              ) : (
                <PairScore
                  home={text(row.home, "int")}
                  away={text(row.away, "int")}
                  winner={row.fewer ? leadingSide(row.away, row.home) : leadingSide(row.home, row.away)}
                />
              )}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

// ── Turning points ───────────────────────────────────────────────────────────

function TurningPoints({ teams, feed, onTime }: Readonly<{ teams: readonly [DlTeam, DlTeam]; feed: MatchFeed; onTime: (t: number) => void }>) {
  const t = useTranslations();
  const text = useStatFormat();
  const series = useMemo(() => soulsSeries(teams[0].players, teams[1].players, feed), [teams, feed]);
  if (series.length < 2) return null;
  const points = series.map((point) => ({ t: point.t, diff: point.home - point.away }));
  const peak = (side: Side) =>
    points.reduce<{ t: number; diff: number } | null>((best, point) => {
      const lead = side === "home" ? point.diff : -point.diff;
      return lead > 0 && (!best || lead > (side === "home" ? best.diff : -best.diff)) ? point : best;
    }, null);
  let changes = 0;
  for (let index = 1; index < points.length; index += 1) {
    const before = Math.sign(points[index - 1].diff);
    const now = Math.sign(points[index].diff);
    if (before !== 0 && now !== 0 && before !== now) changes += 1;
  }
  const name = (side: Side) => (side === "home" ? teams[0].name : teams[1].name);
  const row = cn("grid content-start gap-1.5 border-t pt-3 sm:border-t-0 sm:border-s sm:ps-5 sm:pt-0 sm:first:border-s-0 sm:first:ps-0", HAIRLINE);
  const firstObjective = [...feed.objectives].sort((a, b) => a.t - b.t)[0];
  const clock = (time: number) => (
    <Button type="button" variant="link" size="inline" onClick={() => onTime(time)} className="aqt-tnum">
      {formatClock(time)}
    </Button>
  );
  return (
    <div>
      <dl className="m-0 grid gap-4 sm:grid-cols-2 lg:grid-cols-4 lg:gap-5">
        <div className={row}>
          <Eyebrow as="dt">{t("matches.deadlock.breakdown.biggestLead")}</Eyebrow>
          {(["home", "away"] as const).map((side) => {
            const point = peak(side);
            return (
              <dd key={side} className="m-0 flex items-baseline gap-1.5 text-body">
                <span className="truncate font-semibold" style={{ color: SEAT[side] }}>
                  {name(side)}
                </span>
                {point ? (
                  <span className="aqt-tnum">
                    +{text(Math.abs(point.diff), "int")}
                    <span className={cn("text-caption", DIM)}> · {clock(point.t)}</span>
                  </span>
                ) : (
                  <span className={FAINT}>{t("matches.deadlock.breakdown.neverLed")}</span>
                )}
              </dd>
            );
          })}
        </div>
        <div className={row}>
          <Eyebrow as="dt">{t("matches.deadlock.breakdown.leadChanges")}</Eyebrow>
          <dd className="aqt-tnum m-0 text-body font-semibold">{changes}</dd>
        </div>
        {firstObjective ? (
          <div className={row}>
            <Eyebrow as="dt">{t("matches.deadlock.breakdown.firstObjective")}</Eyebrow>
            <dd className="m-0 text-body">
              {clock(firstObjective.t)} ·{" "}
              {firstObjective.owner ? (
                <span className="font-semibold" style={{ color: SEAT[firstObjective.owner === "home" ? "away" : "home"] }}>
                  {name(firstObjective.owner === "home" ? "away" : "home")}
                </span>
              ) : null}
            </dd>
          </div>
        ) : null}
        {feed.midBoss.length ? (
          <div className={row}>
            <Eyebrow as="dt">{t("matches.deadlock.breakdown.midBoss")}</Eyebrow>
            {feed.midBoss.map((boss) => (
              <dd key={boss.t} className="m-0 text-body">
                {clock(boss.t)} ·{" "}
                {boss.claimer ? (
                  <span className="font-semibold" style={{ color: SEAT[boss.claimer] }}>
                    {name(boss.claimer)}
                  </span>
                ) : null}
                {boss.killer && boss.claimer && boss.killer !== boss.claimer ? (
                  <span className={cn("text-caption", DIM)}> · {t("matches.deadlock.breakdown.stolen")}</span>
                ) : null}
              </dd>
            ))}
          </div>
        ) : null}
      </dl>
    </div>
  );
}

// ── Players over time ────────────────────────────────────────────────────────

type Series = "net_worth" | "player_damage";

function PlayerLines({ teams, feed, t: moment, durationS }: Readonly<{ teams: readonly [DlTeam, DlTeam]; feed: MatchFeed; t: number; durationS: number }>) {
  const t = useTranslations();
  const text = useStatFormat();
  const [series, setSeries] = useState<Series>("net_worth");
  const [focus, setFocus] = useState<number | null>(null);
  const players = teams.flatMap((team) => team.players);
  const lines = players
    .map((player) => ({
      player,
      points: [{ t: 0, v: 0 }, ...(feed.snapshots.get(player.memberId) ?? []).map((snap) => ({ t: snap.t, v: snap.values[series] ?? 0 }))]
    }))
    .filter((line) => line.points.length > 1);
  if (!lines.length) return null;
  const t1 = Math.max(...lines.flatMap((line) => line.points.map((point) => point.t)));
  const top = Math.max(1, ...lines.flatMap((line) => line.points.map((point) => point.v)));
  const x = (time: number) => PAD.left + (time / t1) * (W - PAD.left - PAD.right);
  const y = (value: number) => PAD.top + (1 - value / top) * (H - PAD.top - PAD.bottom);
  const label = series === "net_worth" ? t("matches.deadlock.colTitle.net_worth") : t("matches.deadlock.colTitle.player_damage");
  const ordered = [...lines].sort((a, b) => (a.player.memberId === focus ? 1 : 0) - (b.player.memberId === focus ? 1 : 0));

  return (
    <div className="grid gap-4">
      <ToggleGroup
        value={series}
        onValueChange={(value) => value && setSeries(value as Series)}
        variant="pill"
        size="sm"
        aria-label={t("matches.deadlock.breakdown.graphSeries")}
        className="self-start"
      >
        <ToggleGroupItem value="net_worth">{t("matches.deadlock.colTitle.net_worth")}</ToggleGroupItem>
        <ToggleGroupItem value="player_damage">{t("matches.deadlock.colTitle.player_damage")}</ToggleGroupItem>
      </ToggleGroup>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(260px,1fr)] lg:gap-x-7">
        <div className="min-w-0 overflow-x-auto overscroll-x-contain [scrollbar-width:thin]">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            aria-label={t("matches.deadlock.breakdown.graphAria", { series: label })}
            className={cn("block h-auto w-full min-w-[520px] rounded-xl border bg-[color:var(--aqt-overlay-1)]", HAIRLINE)}
          >
            {ticksOf(t1).map((s) => (
              <line key={s} x1={x(s)} x2={x(s)} y1={PAD.top} y2={H - PAD.bottom} stroke="var(--aqt-border)" />
            ))}
            <line x1={PAD.left} x2={W - PAD.right} y1={y(0)} y2={y(0)} stroke="var(--aqt-border-3)" />
            <text x={PAD.left - 8} y={y(top) + 4} textAnchor="end" className="fill-[color:var(--aqt-fg-faint)] text-label font-medium">
              {text(top, "int")}
            </text>
            <text x={PAD.left - 8} y={y(0) + 4} textAnchor="end" className="fill-[color:var(--aqt-fg-faint)] text-label font-medium">
              0
            </text>
            {ticksOf(t1).map((s) => (
              <text key={s} x={x(s)} y={H - 8} textAnchor="middle" className="fill-[color:var(--aqt-fg-faint)] text-label font-medium">
                {formatClock(s)}
              </text>
            ))}
            {ordered.map(({ player, points }) => {
              const dim = focus !== null && focus !== player.memberId;
              return (
                <path
                  key={player.memberId}
                  d={points.map((point, index) => `${index ? "L" : "M"}${x(point.t).toFixed(1)},${y(point.v).toFixed(1)}`).join("")}
                  fill="none"
                  stroke={SEAT[player.side]}
                  strokeWidth={focus === player.memberId ? 2.5 : 1.5}
                  strokeLinejoin="round"
                  opacity={dim ? 0.15 : 0.85}
                >
                  <title>{`${player.display.name} · ${text(points.at(-1)!.v, "int")}`}</title>
                </path>
              );
            })}
            {moment < durationS ? (
              <line x1={x(moment)} x2={x(moment)} y1={PAD.top - 6} y2={H - PAD.bottom} stroke="var(--aqt-fg)" strokeWidth={1} />
            ) : null}
          </svg>
        </div>
        <ul className="m-0 grid content-start gap-x-4 gap-y-0.5 sm:grid-cols-2" aria-label={label}>
          {[...lines]
            .sort((a, b) => b.points.at(-1)!.v - a.points.at(-1)!.v)
            .map(({ player, points }) => (
              <li key={player.memberId}>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-pressed={focus === player.memberId}
                  onMouseEnter={() => setFocus(player.memberId)}
                  onMouseLeave={() => setFocus(null)}
                  onFocus={() => setFocus(player.memberId)}
                  onBlur={() => setFocus(null)}
                  className="w-full justify-start gap-2 px-1.5"
                >
                  <SeatBar side={player.side} />
                  {player.hero ? <CatalogEntityImage entity={player.hero} size={20} decorative /> : null}
                  <span className="min-w-0 flex-1 truncate text-start">{player.display.name}</span>
                  <span className={cn("aqt-tnum", MUTED)}>{text(points.at(-1)!.v, "int")}</span>
                </Button>
              </li>
            ))}
        </ul>
      </div>
    </div>
  );
}

// ── Who carried ──────────────────────────────────────────────────────────────

const CARRY_STATS = ["player_damage", "net_worth", "player_healing", "boss_damage"] as const;
const CARRY_MIX = [100, 76, 58, 44, 34, 28];

function CarryRow({ team, code }: Readonly<{ team: DlTeam; code: string }>) {
  const t = useTranslations();
  const text = useStatFormat();
  const total = teamSum(team, code) ?? 0;
  const shares = team.players
    .map((player) => ({ player, value: player.stats[code] ?? 0 }))
    .filter((entry) => entry.value > 0)
    .sort((a, b) => b.value - a.value)
    .map((entry) => ({ ...entry, share: total > 0 ? entry.value / total : 0 }));
  const pct = (share: number) => Math.round(share * 100);
  const nameOf = (player: DlPlayer) => player.display.name;
  const summary = shares.map(({ player, share }) => `${nameOf(player)} ${pct(share)}%`);
  return (
    <div
      role="img"
      aria-label={`${team.name}, ${t(`matches.deadlock.colTitle.${code}` as never)}: ${summary.join(", ") || t("matches.breakdown.noData")}`}
      className="grid min-h-8 grid-cols-[3px_minmax(0,1fr)_72px] items-center gap-x-2.5 gap-y-0.5"
    >
      <SeatBar side={team.side} />
      {total > 0 ? (
        <div className="flex h-6 min-w-0 gap-0.5">
          {shares.map(({ player, value, share }, index) => {
            const mix = CARRY_MIX[Math.min(index, CARRY_MIX.length - 1)];
            return (
              <span
                key={player.memberId}
                title={`${nameOf(player)}: ${text(value, "int")} · ${pct(share)}%`}
                className="block min-w-0 overflow-hidden whitespace-nowrap rounded-sm px-2 text-label font-semibold leading-6"
                style={{
                  width: `${share * 100}%`,
                  background: `color-mix(in srgb, ${SEAT[team.side]} ${mix}%, var(--aqt-card))`,
                  color: mix >= 70 ? "var(--aqt-bg)" : "var(--aqt-fg)"
                }}
              >
                {share >= 0.2 ? <span className="hidden sm:inline">{`${nameOf(player)}\u00a0`}</span> : null}
                {share >= 0.09 ? `${pct(share)}%` : null}
              </span>
            );
          })}
        </div>
      ) : (
        <span className={cn("text-caption", DIM)}>{t("matches.breakdown.noData")}</span>
      )}
      <span className={cn("aqt-tnum text-end text-caption", MUTED)}>{text(total, "int")}</span>
    </div>
  );
}

// ── Where souls came from ────────────────────────────────────────────────────

const SOURCES = [
  // Away from the side hues (amber, sapphire): a source must never read as a team.
  { key: "laneCreeps", codes: ["souls_lane_creeps"], color: "var(--aqt-teal)" },
  { key: "neutrals", codes: ["souls_neutrals"], color: "var(--aqt-emerald)" },
  { key: "heroes", codes: ["souls_players", "souls_assists"], color: "var(--aqt-rose)" },
  { key: "bosses", codes: ["souls_bosses"], color: "var(--aqt-violet)" },
  {
    key: "other",
    codes: ["souls_treasure", "souls_breakables", "souls_denies", "souls_team_bonus", "souls_items"],
    color: "var(--aqt-border-3)"
  }
] as const;

function SoulsSources({ teams }: Readonly<{ teams: readonly [DlTeam, DlTeam] }>) {
  const t = useTranslations();
  const text = useStatFormat();
  const players = teams.flatMap((team) => team.players);
  const parts = (player: DlPlayer) =>
    SOURCES.map((source) => ({ ...source, value: source.codes.reduce((total, code) => total + (player.stats[code] ?? 0), 0) }));
  if (!players.some((player) => parts(player).some((part) => part.value > 0))) return null;
  const label = (key: string) => t(`matches.deadlock.breakdown.source.${key}` as never);
  return (
    <div className="grid gap-3">
      <ul className={cn("m-0 flex flex-wrap gap-x-4 gap-y-1.5 text-label", DIM)}>
        {SOURCES.map((source) => (
          <li key={source.key} className="inline-flex items-center gap-1.5">
            <span aria-hidden className="size-2.5 rounded-sm" style={{ background: source.color }} />
            {label(source.key)}
          </li>
        ))}
      </ul>
      <div className="grid gap-x-9 gap-y-1.5 lg:grid-cols-2">
        {teams.map((team) => (
          <ul key={team.id} className="m-0 grid gap-1.5" aria-label={team.name}>
            {team.players.map((player) => {
              const split = parts(player);
              const total = split.reduce((sum, part) => sum + part.value, 0);
              const summary = split
                .filter((part) => part.value > 0)
                .map((part) => `${label(part.key)} ${Math.round((part.value / total) * 100)}%`)
                .join(", ");
              return (
                <li key={player.memberId} className="grid grid-cols-[3px_22px_minmax(0,9rem)_minmax(0,1fr)] items-center gap-x-2.5">
                  <SeatBar side={team.side} />
                  {player.hero ? <CatalogEntityImage entity={player.hero} size={22} decorative /> : <span />}
                  <span className={cn("truncate text-caption", MUTED)}>{player.display.name}</span>
                  <div role="img" aria-label={`${player.display.name}: ${summary}`} className="flex h-2.5 min-w-0 gap-px overflow-hidden rounded-full">
                    {total > 0
                      ? split.map((part) =>
                          part.value > 0 ? (
                            <span
                              key={part.key}
                              title={`${label(part.key)}: ${text(part.value, "int")} · ${Math.round((part.value / total) * 100)}%`}
                              className="block h-full"
                              style={{ width: `${(part.value / total) * 100}%`, background: part.color }}
                            />
                          ) : null
                        )
                      : null}
                  </div>
                </li>
              );
            })}
          </ul>
        ))}
      </div>
    </div>
  );
}

// ── The tab ──────────────────────────────────────────────────────────────────

interface BreakdownProps {
  teams: readonly [DlTeam, DlTeam];
  feed: MatchFeed | null;
  t: number;
  durationS: number;
  onTime: (t: number) => void;
}

export default function Breakdown({ teams, feed, t: moment, durationS, onTime }: Readonly<BreakdownProps>) {
  const t = useTranslations();
  return (
    <div className="grid gap-9">
      <Totals teams={teams} />

      <Section title={t("matches.deadlock.breakdown.turningTitle")} hint={t("matches.deadlock.breakdown.turningHint")}>
        {feed ? <TurningPoints teams={teams} feed={feed} onTime={onTime} /> : <Skeleton className="h-24 w-full" />}
      </Section>

      <Section title={t("matches.deadlock.breakdown.graphTitle")} hint={t("matches.deadlock.breakdown.graphHint")}>
        {feed ? (
          <PlayerLines teams={teams} feed={feed} t={moment} durationS={durationS} />
        ) : (
          <Skeleton className="aspect-[1000/240] min-h-40 w-full" />
        )}
      </Section>

      <Section title={t("matches.breakdown.carryTitle")} hint={t("matches.breakdown.carryHint")}>
        <div className="grid gap-x-9 gap-y-5 lg:grid-cols-2">
          {CARRY_STATS.map((code) => (
            <div key={code}>
              <Eyebrow className="mb-2 block">{t(`matches.deadlock.colTitle.${code}` as never)}</Eyebrow>
              {teams.map((team) => (
                <CarryRow key={team.id} team={team} code={code} />
              ))}
            </div>
          ))}
        </div>
      </Section>

      <Section title={t("matches.deadlock.breakdown.sourcesTitle")} hint={t("matches.deadlock.breakdown.sourcesHint")}>
        <SoulsSources teams={teams} />
      </Section>
    </div>
  );
}
