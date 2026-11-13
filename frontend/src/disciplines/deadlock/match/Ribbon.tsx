"use client";

import { useId, useMemo, type PointerEvent } from "react";
import { useTranslations } from "next-intl";
import { CircleHelp, MoveHorizontal, Skull, type LucideIcon } from "lucide-react";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Popover, PopoverContent, PopoverTrigger } from "@craazzzyyfoxx/admin-kit/ui/popover";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@craazzzyyfoxx/admin-kit/ui/tooltip";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { cn } from "@/lib/utils";
import { groupKills, soulsSeries, type DlTeam, type MatchFeed, type Side } from "./model";
import { DIM, FAINT, SEAT, formatClock, sideVars, useStatFormat, useWidth } from "./parts";
import { LANE_COLOR, LANE_KEY, OBJECTIVE_ICON, objectiveOf, type ObjectiveKind } from "./objectives";

const other = (side: Side): Side => (side === "home" ? "away" : "home");

/** Badge sizes and the rows they stack in, px: a mark that would touch its neighbour goes up a row. */
const BADGE = 18;
const BADGE_BIG = 22;
const ROW = 22;
const MAX_ROWS = 2;
/** Legend order of the structures; the Patron and its core share one entry. */
const LEGEND_KINDS: ObjectiveKind[] = ["guardian", "walker", "baseGuardian", "shrine", "core"];

interface Mark {
  key: string;
  t: number;
  /** The side that did it (destroyed the structure, claimed the boss): the badge's colour and edge. */
  side: Side;
  Icon: LucideIcon;
  /** The match-deciding structures, drawn filled. */
  big: boolean;
  /** What fell, e.g. "Walker" or "Mid boss". */
  title: string;
  /** The lane's `CMsgLaneColor`, for a lane structure. */
  lane: number | null;
  /** What the side did, after its name ("destroyed it", "stole the mid boss"). */
  verb: string;
  /** Where it stands among its kind: "Team 1's objective #5". */
  ordinal: string;
}

/** Each side's marks in time order, packed into rows so no two badges overlap (up to `MAX_ROWS`, then they may). */
function pack(marks: readonly Mark[], width: number, end: number) {
  const placed: { mark: Mark; left: number; row: number; size: number }[] = [];
  for (const side of ["home", "away"] as const) {
    const rights: number[] = [];
    for (const mark of marks.filter((candidate) => candidate.side === side).sort((a, b) => a.t - b.t)) {
      const size = mark.big ? BADGE_BIG : BADGE;
      const left = Math.min(Math.max(0, (Math.min(mark.t, end) / end) * width - size / 2), Math.max(0, width - size));
      let row = rights.findIndex((right) => right + 2 <= left);
      if (row === -1 && rights.length < MAX_ROWS) row = rights.length;
      if (row === -1) row = rights.indexOf(Math.min(...rights));
      rights[row] = left + size;
      placed.push({ mark, left, row, size });
    }
  }
  return placed;
}

/** A round badge holding a structure's or the boss's glyph; `tone` is a side colour or the neutral legend tone. */
function Badge({ Icon, tone, big = false, size = BADGE }: Readonly<{ Icon: LucideIcon; tone: string; big?: boolean; size?: number }>) {
  return (
    <span
      className="grid shrink-0 place-items-center rounded-full border-[1.5px]"
      style={{
        width: size,
        height: size,
        borderColor: tone,
        color: big ? "var(--aqt-card)" : tone,
        background: big ? tone : "var(--aqt-card)"
      }}
    >
      <Icon aria-hidden className={size >= 28 ? "size-4" : "size-3"} strokeWidth={2.25} />
    </span>
  );
}

/** The card a mark opens on hover: what fell and where, who did it and when, its place in the match. */
function MarkCard({ mark, team }: Readonly<{ mark: Mark; team: string }>) {
  const tr = useTranslations();
  return (
    <div className="grid min-w-56 gap-2.5">
      <div className="flex items-center gap-2.5">
        <Badge Icon={mark.Icon} tone={SEAT[mark.side]} big={mark.big} size={30} />
        <div className="min-w-0">
          <p className="m-0 truncate text-body font-semibold text-[color:var(--aqt-fg)]">{mark.title}</p>
          {mark.lane !== null ? (
            <p className={cn("m-0 flex items-center gap-1.5 text-caption", DIM)}>
              <span aria-hidden className="size-2 rotate-45" style={{ background: LANE_COLOR[mark.lane] }} />
              {tr(`matches.deadlock.lanes.name.${LANE_KEY[mark.lane] ?? "unknown"}` as never)}
            </p>
          ) : null}
        </div>
        <span className="aqt-tnum ms-auto ps-3 font-display text-ui font-semibold text-[color:var(--aqt-fg)]">{formatClock(mark.t)}</span>
      </div>
      <Separator />
      <p className="m-0 text-caption">
        <span className="font-semibold" style={{ color: SEAT[mark.side] }}>
          {team}
        </span>{" "}
        <span className="text-[color:var(--aqt-fg-muted)]">{mark.verb}</span>
      </p>
      <p className={cn("m-0 flex items-center justify-between gap-3 text-label", FAINT)}>
        <span>{mark.ordinal}</span>
        <span>{tr("matches.deadlock.ribbon.tip.jump")}</span>
      </p>
    </div>
  );
}

interface RibbonProps {
  teams: readonly [DlTeam, DlTeam];
  feed: MatchFeed | null;
  durationS: number;
  t: number;
  onTime: (t: number) => void;
}

/**
 * The whole match on one sticky strip, and the moment the rest of the view shows. The souls lead fills toward the
 * side ahead; kills tick along the edges, destroyed structures sit on the edge of the side that took them, the mid
 * boss by the side that claimed it, fights shade the strip. The team names stand by their halves, the clock between
 * them; the figures live in the team cards below. Dragging the strip moves the moment.
 */
export default function Ribbon({ teams, feed, durationS, t, onTime }: Readonly<RibbonProps>) {
  const tr = useTranslations();
  const text = useStatFormat();
  const uid = useId().replace(/:/g, "");
  const [plotRef, plotWidth, plotNode] = useWidth<HTMLDivElement>();
  const atEnd = t >= durationS;

  const series = useMemo(() => (feed ? soulsSeries(teams[0].players, teams[1].players, feed) : []), [teams, feed]);
  const fights = useMemo(() => (feed ? groupKills(feed.kills).filter((group) => group.no !== null) : []), [feed]);

  if (!feed) return <Skeleton className="h-32 w-full rounded-xl" />;

  const end = Math.max(durationS, 1);
  const x = (time: number) => (Math.min(time, end) / end) * 1000;
  const pct = (time: number) => `${(Math.min(time, end) / end) * 100}%`;
  const points = series.map((point) => ({ t: point.t, diff: point.home - point.away }));
  const top = Math.max(1000, ...points.map((point) => Math.abs(point.diff)));
  const y = (diff: number) => 50 - (diff / top) * 42;
  const line = points.map((point, index) => `${index ? "L" : "M"}${x(point.t).toFixed(1)},${y(point.diff).toFixed(2)}`).join("");
  const area = points.length ? `${line}L${x(points.at(-1)!.t)},50L0,50Z` : "";
  const ticks: number[] = [];
  for (let s = 300; s < end; s += 300) ticks.push(s);

  const last = points.at(-1)?.diff ?? 0;
  const ariaLabel = `${tr("matches.deadlock.breakdown.soulsTitle")}: ${
    last === 0
      ? tr("matches.deadlock.breakdown.soulsEven")
      : tr("matches.deadlock.breakdown.soulsAria", {
          team: last > 0 ? teams[0].name : teams[1].name,
          lead: text(Math.abs(last), "int")
        })
  }`;

  const teamName = (side: Side) => (side === "home" ? teams[0].name : teams[1].name);
  const taken = { home: 0, away: 0 };
  const objectives = [...feed.objectives].filter((objective) => objective.owner).sort((a, b) => a.t - b.t);
  const marks: Mark[] = [
    ...objectives.map((objective, index): Mark => {
      const { kind, lane } = objectiveOf(objective.objective);
      const by = other(objective.owner!);
      taken[by] += 1;
      return {
        key: `o${index}`,
        t: objective.t,
        side: by,
        Icon: OBJECTIVE_ICON[kind],
        big: kind === "patron" || kind === "core",
        title: tr(`matches.deadlock.timeline.objective.${kind}` as never),
        lane,
        verb: tr("matches.deadlock.ribbon.tip.destroyed", { owner: teamName(objective.owner!) }),
        ordinal: tr("matches.deadlock.ribbon.tip.objectiveNo", { team: teamName(by), n: taken[by] })
      };
    }),
    ...feed.midBoss.flatMap((boss, index): Mark[] =>
      boss.claimer
        ? [
            {
              key: `b${index}`,
              t: boss.t,
              side: boss.claimer,
              Icon: Skull,
              big: false,
              title: tr("matches.deadlock.breakdown.midBoss"),
              lane: null,
              verb: tr(boss.killer && boss.killer !== boss.claimer ? "matches.deadlock.timeline.midBossStolen" : "matches.deadlock.timeline.midBossTaken"),
              ordinal: tr("matches.deadlock.ribbon.tip.bossNo", { n: index + 1 })
            }
          ]
        : []
    )
  ];
  const kinds = new Set(feed.objectives.map((objective) => objectiveOf(objective.objective).kind));
  const legendKinds = LEGEND_KINDS.filter((kind) => kinds.has(kind) || (kind === "core" && kinds.has("patron")));

  const scrub = (event: PointerEvent<HTMLDivElement>) => {
    const box = plotNode?.getBoundingClientRect();
    if (!box || box.width === 0) return;
    const ratio = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
    // The strip's last sliver is the end: there is no button for it, so it must be easy to hit.
    onTime(ratio >= 0.99 ? durationS : Math.round(ratio * durationS));
  };

  const legend = (
    <div className="grid gap-3">
      <Eyebrow>{tr("matches.deadlock.ribbon.legend.title")}</Eyebrow>
      <ul className={cn("m-0 grid grid-cols-2 gap-x-4 gap-y-2 text-caption", DIM)}>
        <li className="inline-flex items-center gap-1.5">
          <svg aria-hidden width="14" height="12" viewBox="0 0 14 12">
            <rect x="3" y="0" width="2" height="12" rx="1" fill={SEAT.home} />
            <rect x="9" y="0" width="2" height="12" rx="1" fill={SEAT.away} />
          </svg>
          {tr("matches.deadlock.colTitle.kills")}
        </li>
        <li className="inline-flex items-center gap-1.5">
          <svg aria-hidden width="14" height="12" viewBox="0 0 14 12">
            <path d="M0 6 L5 1 L14 1 L14 6 Z" fill={SEAT.home} opacity={0.6} />
            <path d="M0 6 L14 6 L14 11 L7 11 Z" fill={SEAT.away} opacity={0.6} />
          </svg>
          {tr("matches.deadlock.breakdown.soulsTitle")}
        </li>
        <li className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-3 w-3.5 rounded-sm bg-[color:var(--aqt-overlay-4)]" />
          {tr("matches.deadlock.ribbon.legend.fight")}
        </li>
        {legendKinds.map((kind) => (
          <li key={kind} className="inline-flex items-center gap-1.5">
            <Badge Icon={OBJECTIVE_ICON[kind]} tone="var(--aqt-fg-muted)" size={18} />
            {tr(`matches.deadlock.timeline.objective.${kind}` as never)}
          </li>
        ))}
        {feed.midBoss.length ? (
          <li className="inline-flex items-center gap-1.5">
            <Badge Icon={Skull} tone="var(--aqt-fg-muted)" size={18} />
            {tr("matches.deadlock.breakdown.midBoss")}
          </li>
        ) : null}
      </ul>
      <p className={cn("m-0 text-caption", FAINT)}>{tr("matches.deadlock.ribbon.legend.colour")}</p>
      <Separator />
      <p className={cn("m-0 flex gap-2 text-caption", DIM)}>
        <MoveHorizontal aria-hidden className="mt-0.5 size-4 shrink-0" />
        {tr("matches.deadlock.ribbon.hint")}
      </p>
    </div>
  );
  const name = (team: DlTeam) => (
    <p className="m-0 truncate text-label font-semibold" style={{ color: SEAT[team.side] }} title={team.name}>
      {team.name}
    </p>
  );

  return (
    <section
      aria-label={tr("matches.deadlock.ribbon.title")}
      // Pinned under the site header on a page; in the match dialog flush with the scroller's edge (minus its `py-4`).
      // On a phone the names and the clock share one row above a full-width strip.
      className="z-20 grid grid-cols-[minmax(0,6.5rem)_minmax(0,1fr)_auto] items-start gap-x-4 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-4 pb-1.5 pt-3 sm:sticky sm:top-[var(--aqt-sticky-top)] max-sm:grid-cols-[minmax(0,1fr)_auto] max-sm:gap-x-2.5 max-sm:px-3 [[role=dialog]_&]:-top-4"
    >
      <div className="flex h-24 flex-col justify-between max-sm:h-auto max-sm:flex-row max-sm:items-center max-sm:gap-3">
        {name(teams[0])}
        <div className="max-sm:text-center">
          <p className="aqt-tnum m-0 font-display text-title font-semibold" aria-live="polite">
            {formatClock(atEnd ? durationS : t)}
          </p>
          <p className={cn("m-0 text-label", DIM)}>
            {atEnd ? tr("matches.deadlock.ribbon.end") : tr("matches.deadlock.ribbon.of", { time: formatClock(durationS) })}
          </p>
        </div>
        {name(teams[1])}
      </div>

      <div className="min-w-0 max-sm:col-span-2 max-sm:row-start-2 max-sm:mt-2">
        {/* The strip is the control: drag or click to move, arrows by 10 s (Shift: a minute), Home / End. */}
        <div
          ref={plotRef}
          role="slider"
          tabIndex={0}
          aria-label={tr("matches.deadlock.ribbon.time")}
          aria-valuemin={0}
          aria-valuemax={durationS}
          aria-valuenow={Math.min(t, durationS)}
          aria-valuetext={formatClock(Math.min(t, durationS))}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
            scrub(event);
          }}
          onPointerMove={(event) => {
            if (event.buttons === 1) scrub(event);
          }}
          onKeyDown={(event) => {
            const step = event.shiftKey ? 60 : 10;
            const next =
              event.key === "ArrowLeft" || event.key === "ArrowDown"
                ? t - step
                : event.key === "ArrowRight" || event.key === "ArrowUp"
                  ? t + step
                  : event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? durationS
                      : null;
            if (next === null) return;
            event.preventDefault();
            onTime(Math.min(durationS, Math.max(0, next)));
          }}
          className="relative h-24 cursor-ew-resize touch-none select-none rounded-md focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] focus-visible:ring-offset-4 focus-visible:ring-offset-[color:var(--aqt-card)]"
        >
          <svg viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden className="absolute inset-0 size-full">
            <defs>
              <clipPath id={`${uid}-up`}>
                <rect x={0} y={0} width={1000} height={50} />
              </clipPath>
              <clipPath id={`${uid}-dn`}>
                <rect x={0} y={50} width={1000} height={50} />
              </clipPath>
            </defs>
            {fights.map((fight) => (
              <rect
                key={fight.no}
                x={x(fight.from) - 1.5}
                y={7}
                width={Math.max(3, x(fight.to) - x(fight.from) + 3)}
                height={86}
                className="fill-[color:var(--aqt-overlay-2)]"
              />
            ))}
            {ticks.map((s) => (
              <line key={s} x1={x(s)} x2={x(s)} y1={7} y2={93} stroke="var(--aqt-border)" vectorEffect="non-scaling-stroke" />
            ))}
            <path d={area} fill={SEAT.home} opacity={0.34} clipPath={`url(#${uid}-up)`} />
            <path d={area} fill={SEAT.away} opacity={0.34} clipPath={`url(#${uid}-dn)`} />
            <line x1={0} x2={1000} y1={50} y2={50} stroke="var(--aqt-border-3)" vectorEffect="non-scaling-stroke" />
            <path d={line} fill="none" stroke="var(--aqt-fg-muted)" strokeWidth={1.5} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
            {feed.kills.map((kill, index) =>
              kill.side ? (
                <rect
                  key={index}
                  x={x(kill.t) - 0.6}
                  y={kill.side === "home" ? 0 : 95}
                  width={1.2}
                  height={5}
                  fill={SEAT[kill.side]}
                  opacity={0.85}
                />
              ) : null
            )}
            {atEnd ? null : <rect x={x(t)} y={0} width={1000 - x(t)} height={100} className="fill-[color:var(--aqt-card)]" opacity={0.62} />}
          </svg>

          {plotWidth > 0 ? (
            <TooltipProvider>
              {pack(marks, plotWidth, end).map(({ mark, left, row, size }) => (
                <Tooltip key={mark.key}>
                  {/* A press on a mark still moves the moment: the strip handles the pointer. */}
                  <TooltipTrigger asChild>
                    <span
                      aria-hidden
                      className={cn(
                        "absolute rounded-full transition-shadow hover:ring-2 hover:ring-[color:var(--aqt-fg-muted)] hover:ring-offset-1 hover:ring-offset-[color:var(--aqt-card)]",
                        mark.t > t && "opacity-30"
                      )}
                      style={{ left, ...(mark.side === "home" ? { top: 6 + row * ROW } : { bottom: 6 + row * ROW }) }}
                    >
                      <Badge Icon={mark.Icon} tone={SEAT[mark.side]} big={mark.big} size={size} />
                    </span>
                  </TooltipTrigger>
                  <TooltipContent
                    side={mark.side === "home" ? "top" : "bottom"}
                    sideOffset={8}
                    style={sideVars(teams)}
                    className="max-w-sm px-3.5 py-3 text-start"
                  >
                    <MarkCard mark={mark} team={teamName(mark.side)} />
                  </TooltipContent>
                </Tooltip>
              ))}
            </TooltipProvider>
          ) : null}
          {atEnd ? null : (
            <span aria-hidden className="pointer-events-none absolute inset-y-0 w-px -translate-x-1/2 bg-[color:var(--aqt-fg)]" style={{ left: pct(t) }}>
              <span className="absolute -top-1 left-1/2 size-2 -translate-x-1/2 rounded-full bg-[color:var(--aqt-fg)]" />
            </span>
          )}
        </div>

        <div className="relative mt-0.5 h-4">
          {ticks.map((s, index) => (
            // Every other label on a phone, where five-minute labels would touch.
            <span
              key={s}
              className={cn("aqt-tnum absolute -translate-x-1/2 text-label", FAINT, index % 2 === 0 && "max-md:hidden")}
              style={{ left: pct(s) }}
            >
              {formatClock(s)}
            </span>
          ))}
        </div>
      </div>

      <Popover>
        <PopoverTrigger asChild>
          <Button type="button" variant="ghost" size="icon-sm" aria-label={tr("matches.deadlock.ribbon.legend.open")}>
            <CircleHelp aria-hidden className="size-4" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" style={sideVars(teams)} className="w-80 max-w-[calc(100vw-2rem)]">
          {legend}
        </PopoverContent>
      </Popover>
      <p className="sr-only">{ariaLabel}</p>
    </section>
  );
}
