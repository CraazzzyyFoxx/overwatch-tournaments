"use client";

import { useId, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import {
  LANE_CUTOFF_S,
  LANE_STRUCTURES,
  laneSnapshot,
  laneStructures,
  readLanes,
  soulsSeries,
  type DlPlayer,
  type DlTeam,
  type Lane,
  type MatchFeed,
  type Side
} from "./model";
import { LANE_COLOR, LANE_KEY } from "./objectives";
import { DIM, FAINT, MUTED, SEAT, SEAT_TEXT, SeatBar, formatClock, useStatFormat } from "./parts";

/** What a lane is compared on, from the laning sample; `true` when fewer is better. */
const ROWS: [code: string, fewer: boolean][] = [
  ["net_worth", false],
  ["kills", false],
  ["deaths", true],
  ["assists", false],
  ["creep_kills", false],
  ["denies", false],
  ["player_damage", false],
  ["boss_damage", false],
  ["player_damage_taken", true]
];

const other = (side: Side): Side => (side === "home" ? "away" : "home");

type Values = Record<string, number>;

/** One lane read at the laning sample: each player's figures, the sides' sums and who came out ahead. */
function readLane(lane: Lane, feed: MatchFeed) {
  const valuesOf = (player: DlPlayer): Values => laneSnapshot(feed, player.memberId)?.values ?? {};
  const sum = (players: DlPlayer[], code: string) => players.reduce((total, player) => total + (valuesOf(player)[code] ?? 0), 0);
  const souls = { home: sum(lane.home, "net_worth"), away: sum(lane.away, "net_worth") };
  const winner: Side | null = souls.home === souls.away ? null : souls.home > souls.away ? "home" : "away";
  const loser = winner === "home" ? souls.away : souls.home;
  const lead = winner && loser > 0 ? (Math.max(souls.home, souls.away) - loser) / loser : null;
  const series = soulsSeries(lane.home, lane.away, feed);
  return { valuesOf, sum, winner, lead, series, early: series.filter((point) => point.t > 0 && point.t <= LANE_CUTOFF_S) };
}

const kda = (players: DlPlayer[], valuesOf: (player: DlPlayer) => Values) => {
  const total = (code: string) => players.reduce((sum, player) => sum + (valuesOf(player)[code] ?? 0), 0);
  return `${total("kills")}/${total("deaths")}/${total("assists")}`;
};

function Heroes({ players, align }: Readonly<{ players: DlPlayer[]; align: "start" | "end" }>) {
  return (
    <span className={cn("flex shrink-0 -space-x-2", align === "end" && "flex-row-reverse space-x-reverse")}>
      {players.map((player) =>
        player.hero ? (
          <span key={player.memberId} className="rounded-full ring-2 ring-[color:var(--aqt-card)]">
            <CatalogEntityImage entity={player.hero} size={28} decorative />
          </span>
        ) : null
      )}
    </span>
  );
}

/** The lane's souls lead at each early sample: a bar up for the home side, down for the away side. */
function Trend({ points }: Readonly<{ points: { t: number; home: number; away: number }[] }>) {
  const top = Math.max(1, ...points.map((point) => Math.abs(point.home - point.away)));
  return (
    <span className="grid w-full grid-flow-col gap-1.5" aria-hidden>
      {points.map((point) => {
        const diff = point.home - point.away;
        const side: Side = diff >= 0 ? "home" : "away";
        return (
          <span key={point.t} className="grid gap-1">
            <span className="relative block h-7 rounded-sm bg-[color:var(--aqt-overlay-2)]">
              <Separator className="absolute inset-x-0 top-1/2 bg-[color:var(--aqt-border-2)]" />
              <span
                className="absolute inset-x-1 rounded-[2px]"
                style={{
                  background: SEAT[side],
                  height: `${(Math.abs(diff) / top) * 50}%`,
                  ...(side === "home" ? { bottom: "50%" } : { top: "50%" })
                }}
              />
            </span>
            <span className={cn("aqt-tnum text-center text-label", FAINT)}>{formatClock(point.t)}</span>
          </span>
        );
      })}
    </span>
  );
}

function LaneTile({ lane, feed }: Readonly<{ lane: Lane; feed: MatchFeed }>) {
  const t = useTranslations();
  const text = useStatFormat();
  const { valuesOf, winner, lead, early } = readLane(lane, feed);
  return (
    <span className="flex w-full flex-col gap-3 py-1 text-start">
      <span className="flex items-center gap-2">
        <span aria-hidden className="size-2.5 rotate-45" style={{ background: LANE_COLOR[lane.lane] }} />
        <span className="text-ui font-semibold text-[color:var(--aqt-fg)]">{t(`matches.deadlock.lanes.name.${LANE_KEY[lane.lane] ?? "unknown"}` as never)}</span>
        <span className={cn("aqt-tnum ms-auto text-caption font-semibold", winner ? SEAT_TEXT[winner] : FAINT)}>
          {winner && lead !== null ? `+${text(lead, "pct")}` : "="}
        </span>
      </span>
      <span className="flex items-center gap-2">
        <Heroes players={lane.home} align="start" />
        <span className={cn("aqt-tnum text-caption", MUTED)}>{kda(lane.home, valuesOf)}</span>
        <span className={cn("mx-auto text-label", FAINT)}>vs</span>
        <span className={cn("aqt-tnum text-caption", MUTED)}>{kda(lane.away, valuesOf)}</span>
        <Heroes players={lane.away} align="end" />
      </span>
      {early.length ? <Trend points={early} /> : null}
    </span>
  );
}

/** One player's laning: portrait, name, souls and KDA, then the figures his lane is fought over. */
function LanePlayer({ player, values, align }: Readonly<{ player: DlPlayer; values: Values; align: "start" | "end" }>) {
  const t = useTranslations();
  const text = useStatFormat();
  const facts: [string, number][] = [
    ["creep_kills", values.creep_kills ?? 0],
    ["denies", values.denies ?? 0],
    ["player_damage", values.player_damage ?? 0],
    ["player_damage_taken", values.player_damage_taken ?? 0]
  ];
  return (
    <li className={cn("grid gap-3 border-t border-[color:var(--aqt-border)] pt-4 first:border-t-0 first:pt-0", align === "end" && "text-end")}>
      <div className={cn("flex min-w-0 items-center gap-3", align === "end" && "flex-row-reverse")}>
        {player.hero ? <CatalogEntityImage entity={player.hero} size={44} /> : null}
        <div className="min-w-0">
          <p className="m-0 truncate text-ui font-semibold text-[color:var(--aqt-fg)]" title={player.display.name}>
            {player.display.name}
          </p>
          <p className={cn("aqt-tnum m-0 text-caption", DIM)}>
            {text(values.net_worth ?? 0, "int")} {t("matches.deadlock.colTitle.net_worth")} · {values.kills ?? 0}/{values.deaths ?? 0}/{values.assists ?? 0}
          </p>
        </div>
      </div>
      <dl className="m-0 grid grid-cols-2 gap-x-4 gap-y-2">
        {facts.map(([code, value]) => (
          <div key={code} className="min-w-0">
            <Eyebrow as="dt" className="block truncate" title={t(`matches.deadlock.colTitle.${code}` as never)}>
              {t(`matches.deadlock.col.${code}` as never)}
            </Eyebrow>
            <dd className="aqt-tnum m-0 mt-0.5 text-body font-semibold text-[color:var(--aqt-fg)]">{text(value, "int")}</dd>
          </div>
        ))}
      </dl>
    </li>
  );
}

/** The two sides' figure as one bar: each side's share from its own end, the side ahead at full strength. */
function TugRow({ label, home, away, fewer }: Readonly<{ label: string; home: number; away: number; fewer: boolean }>) {
  const text = useStatFormat();
  const total = home + away;
  const better: Side | null = home === away ? null : (home > away) !== fewer ? "home" : "away";
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-baseline gap-x-3 gap-y-1.5">
      <dd className={cn("aqt-tnum col-start-1 row-start-1 m-0 text-body", better === "away" ? DIM : "font-semibold text-[color:var(--aqt-fg)]")}>
        {text(home, "int")}
      </dd>
      <dt className={cn("col-start-2 row-start-1 text-center text-label", FAINT)}>{label}</dt>
      <dd className={cn("aqt-tnum col-start-3 row-start-1 m-0 text-end text-body", better === "home" ? DIM : "font-semibold text-[color:var(--aqt-fg)]")}>
        {text(away, "int")}
      </dd>
      <dd aria-hidden className="relative col-span-3 m-0 flex h-1.5 gap-0.5 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)]">
        {total > 0 ? (
          <>
            <span className="h-full rounded-s-full" style={{ width: `${(home / total) * 100}%`, background: SEAT.home, opacity: better === "away" ? 0.4 : 1 }} />
            <span className="h-full flex-1 rounded-e-full" style={{ background: SEAT.away, opacity: better === "home" ? 0.4 : 1 }} />
          </>
        ) : null}
        <span className="absolute inset-y-0 left-1/2 w-px bg-[color:var(--aqt-card)]" />
      </dd>
    </div>
  );
}

/** The lane's souls lead over the whole match, laning shaded off, and when its structures fell. */
function LaneOverTime({
  lane,
  feed,
  series,
  durationS
}: Readonly<{ lane: Lane; feed: MatchFeed; series: { t: number; home: number; away: number }[]; durationS: number }>) {
  const t = useTranslations();
  const text = useStatFormat();
  const uid = useId().replace(/:/g, "");
  const end = Math.max(durationS, series.at(-1)?.t ?? 1, 1);
  const points = series.map((point) => ({ t: point.t, diff: point.home - point.away }));
  const top = Math.max(500, ...points.map((point) => Math.abs(point.diff)));
  const x = (time: number) => (time / end) * 1000;
  const pct = (time: number) => `${(time / end) * 100}%`;
  const y = (diff: number) => 50 - (diff / top) * 44;
  const line = points.map((point, index) => `${index ? "L" : "M"}${x(point.t).toFixed(1)},${y(point.diff).toFixed(2)}`).join("");
  const area = points.length ? `${line}L${x(points.at(-1)!.t)},50L0,50Z` : "";
  const fell = laneStructures(feed, lane.lane);
  const last = points.at(-1)?.diff ?? 0;
  return (
    <div className="grid gap-2">
      <div className="relative h-28">
        <svg
          viewBox="0 0 1000 100"
          preserveAspectRatio="none"
          role="img"
          aria-label={t("matches.deadlock.lanes.chartAria", { lead: text(Math.abs(last), "int") })}
          className="absolute inset-0 size-full"
        >
          <defs>
            <clipPath id={`${uid}-up`}>
              <rect x={0} y={0} width={1000} height={50} />
            </clipPath>
            <clipPath id={`${uid}-dn`}>
              <rect x={0} y={50} width={1000} height={50} />
            </clipPath>
          </defs>
          <rect x={0} y={0} width={x(LANE_CUTOFF_S)} height={100} className="fill-[color:var(--aqt-overlay-2)]" />
          <path d={area} fill={SEAT.home} opacity={0.34} clipPath={`url(#${uid}-up)`} />
          <path d={area} fill={SEAT.away} opacity={0.34} clipPath={`url(#${uid}-dn)`} />
          <line x1={0} x2={1000} y1={50} y2={50} stroke="var(--aqt-border-3)" vectorEffect="non-scaling-stroke" />
          <line x1={x(LANE_CUTOFF_S)} x2={x(LANE_CUTOFF_S)} y1={0} y2={100} stroke="var(--aqt-border-3)" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
          <path d={line} fill="none" stroke="var(--aqt-fg-muted)" strokeWidth={1.5} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        </svg>
        <span className={cn("absolute top-1 ps-1.5 text-label", FAINT)} style={{ left: 0 }}>
          {t("matches.deadlock.lanes.laning")}
        </span>
        {LANE_STRUCTURES.flatMap((kind) =>
          (["home", "away"] as const).map((owner) => {
            const time = fell[kind][owner];
            if (time === null) return null;
            const by = other(owner);
            return (
              <span
                key={`${kind}-${owner}`}
                aria-hidden
                className="absolute -translate-x-1/2 rotate-45 border border-[color:var(--aqt-card)]"
                style={{
                  left: pct(time),
                  width: kind === "guardian" ? 8 : 10,
                  height: kind === "guardian" ? 8 : 10,
                  background: SEAT[by],
                  ...(by === "home" ? { top: 4 } : { bottom: 4 })
                }}
              />
            );
          })
        )}
      </div>
      <div className="relative h-4">
        {[600, 1200, 1800, 2400].filter((s) => s < end).map((s) => (
          <span key={s} className={cn("aqt-tnum absolute -translate-x-1/2 text-label", FAINT)} style={{ left: pct(s) }}>
            {formatClock(s)}
          </span>
        ))}
      </div>
    </div>
  );
}

function LaneDetail({
  lane,
  feed,
  teams,
  durationS,
  onTime
}: Readonly<{ lane: Lane; feed: MatchFeed; teams: readonly [DlTeam, DlTeam]; durationS: number; onTime: (t: number) => void }>) {
  const t = useTranslations();
  const text = useStatFormat();
  const { valuesOf, sum, winner, lead, series } = readLane(lane, feed);
  const name = (side: Side) => (side === "home" ? teams[0].name : teams[1].name);
  const fell = laneStructures(feed, lane.lane);
  const laneName = t(`matches.deadlock.lanes.name.${LANE_KEY[lane.lane] ?? "unknown"}` as never);

  return (
    <Card asChild className="overflow-hidden p-0">
      <section aria-label={laneName}>
        <header
          className="flex flex-wrap items-end gap-x-6 gap-y-2 border-b border-[color:var(--aqt-border)] px-5 py-4"
        >
          <div className="min-w-0">
            <p className="m-0 flex items-center gap-2">
              <span aria-hidden className="size-2.5 rotate-45" style={{ background: LANE_COLOR[lane.lane] }} />
              <span className="font-display text-title font-semibold">{laneName}</span>
            </p>
            <p className="m-0 mt-1 text-body">
              {winner ? (
                <>
                  <span className={cn("font-semibold", SEAT_TEXT[winner])}>{name(winner)}</span>{" "}
                  <span className={MUTED}>{t("matches.deadlock.lanes.won")}</span>
                </>
              ) : (
                <span className={MUTED}>{t("matches.deadlock.lanes.even")}</span>
              )}
            </p>
          </div>
          {winner && lead !== null ? (
            <p className="m-0 ms-auto text-end">
              <span className={cn("aqt-tnum block font-display text-headline font-semibold", SEAT_TEXT[winner])}>+{text(lead, "pct")}</span>
              <span className={cn("text-caption", DIM)}>{t("matches.deadlock.lanes.leadAt", { time: formatClock(LANE_CUTOFF_S) })}</span>
            </p>
          ) : null}
        </header>

        <div className="grid gap-6 p-5 md:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)_minmax(0,1fr)] lg:gap-8">
          <ul className="m-0 grid content-start gap-4" aria-label={name("home")}>
            <li className="flex items-center gap-2">
              <SeatBar side="home" />
              <span className="truncate text-caption font-semibold">{name("home")}</span>
            </li>
            {lane.home.map((player) => (
              <LanePlayer key={player.memberId} player={player} values={valuesOf(player)} align="start" />
            ))}
          </ul>
          <dl className="m-0 grid content-start gap-3.5 md:order-last md:col-span-2 lg:order-none lg:col-span-1">
            {ROWS.map(([code, fewer]) => (
              <TugRow
                key={code}
                label={t(`matches.deadlock.colTitle.${code}` as never)}
                home={sum(lane.home, code)}
                away={sum(lane.away, code)}
                fewer={fewer}
              />
            ))}
          </dl>
          <ul className="m-0 grid content-start gap-4" aria-label={name("away")}>
            <li className="flex flex-row-reverse items-center gap-2">
              <SeatBar side="away" />
              <span className="truncate text-caption font-semibold">{name("away")}</span>
            </li>
            {lane.away.map((player) => (
              <LanePlayer key={player.memberId} player={player} values={valuesOf(player)} align="end" />
            ))}
          </ul>
        </div>

        <div className="grid gap-6 border-t border-[color:var(--aqt-border)] p-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] lg:gap-8">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3">
              <h4 className="m-0 text-ui font-semibold">{t("matches.deadlock.lanes.chartTitle")}</h4>
              <span className={cn("text-caption", FAINT)}>{t("matches.deadlock.lanes.chartHint")}</span>
            </div>
            <LaneOverTime lane={lane} feed={feed} series={series} durationS={durationS} />
          </div>
          <div className="min-w-0">
            <h4 className="m-0 mb-2 text-ui font-semibold">{t("matches.deadlock.lanes.structures")}</h4>
            <div aria-hidden className="grid grid-cols-[minmax(0,1fr)_5rem_5rem] items-center gap-3 pb-1.5">
              <span />
              <span className={cn("truncate text-end text-label font-semibold", SEAT_TEXT.home)}>{name("home")}</span>
              <span className={cn("truncate text-end text-label font-semibold", SEAT_TEXT.away)}>{name("away")}</span>
            </div>
            <dl className="m-0 grid gap-0">
              {LANE_STRUCTURES.map((kind) => (
                <div key={kind} className="grid grid-cols-[minmax(0,1fr)_5rem_5rem] items-center gap-3 border-t border-[color:var(--aqt-border)] py-2">
                  <dt className={cn("text-caption", MUTED)}>{t(`matches.deadlock.timeline.objective.${kind}` as never)}</dt>
                  {(["home", "away"] as const).map((owner) => {
                    const time = fell[kind][owner];
                    return (
                      <dd key={owner} className="m-0 text-end text-caption">
                        {time === null ? (
                          <span className={FAINT}>
                            <span className="sr-only">{name(owner)}: </span>
                            {t("matches.deadlock.lanes.standing")}
                          </span>
                        ) : (
                          <Button
                            type="button"
                            variant="link"
                            size="inline"
                            onClick={() => onTime(time)}
                            aria-label={t("matches.deadlock.lanes.fellAt", { what: t(`matches.deadlock.timeline.objective.${kind}` as never), team: name(owner), time: formatClock(time) })}
                            className={cn("aqt-tnum", SEAT_TEXT[other(owner)])}
                          >
                            {formatClock(time)}
                          </Button>
                        )}
                      </dd>
                    );
                  })}
                </div>
              ))}
            </dl>
            <p className={cn("m-0 mt-2 text-caption", FAINT)}>{t("matches.deadlock.lanes.structuresHint")}</p>
          </div>
        </div>
      </section>
    </Card>
  );
}

export default function Lanes({
  teams,
  feed,
  durationS,
  onTime
}: Readonly<{ teams: readonly [DlTeam, DlTeam]; feed: MatchFeed | null; durationS: number; onTime: (t: number) => void }>) {
  const t = useTranslations();
  const lanes = useMemo(() => (feed ? readLanes(teams, feed) : []), [teams, feed]);
  const [picked, setPicked] = useState<number | null>(null);

  if (!feed) {
    return (
      <div className="grid gap-4">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} className="h-36 w-full rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-[34rem] w-full rounded-xl" />
      </div>
    );
  }
  if (!lanes.length) return <p className={cn("py-8 text-center text-caption", DIM)}>{t("matches.deadlock.lanes.empty")}</p>;
  const lane = lanes.find((candidate) => candidate.lane === picked) ?? lanes[0];
  // The sample actually read: the cutoff, or the last one before it in a short match.
  const sampled = Math.max(0, ...teams.flatMap((team) => team.players.map((player) => laneSnapshot(feed, player.memberId)?.t ?? 0)));
  const cutoff = Math.min(sampled || LANE_CUTOFF_S, LANE_CUTOFF_S);

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className={cn("m-0 text-caption", FAINT)}>{t("matches.deadlock.lanes.cutoff", { time: formatClock(cutoff) })}</p>
        <Button type="button" variant="link" size="inline" onClick={() => onTime(cutoff)} className="text-caption">
          {t("matches.deadlock.lanes.showOnRibbon")}
        </Button>
      </div>
      {lanes.length > 1 ? (
        <ToggleGroup
          value={String(lane.lane)}
          onValueChange={(value) => value && setPicked(Number(value))}
          variant="card"
          aria-label={t("matches.deadlock.lanes.pick")}
          className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
        >
          {lanes.map((candidate) => (
            <ToggleGroupItem key={candidate.lane} value={String(candidate.lane)} className="py-3">
              <LaneTile lane={candidate} feed={feed} />
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      ) : null}
      <LaneDetail lane={lane} feed={feed} teams={teams} durationS={durationS} onTime={onTime} />
    </div>
  );
}
