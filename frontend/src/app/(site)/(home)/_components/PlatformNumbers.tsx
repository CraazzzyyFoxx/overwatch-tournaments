import type { CSSProperties, ReactNode } from "react";
import { getTranslations } from "next-intl/server";
import { Clock, Trophy, Zap } from "lucide-react";

import { Section, SectionHead } from "@/components/site/open-layout";
import { eyebrowClass } from "@/components/ui/eyebrow";
import Image from "@/components/ui/image";
import { Skeleton } from "@/components/ui/skeleton";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import type { Formatter } from "@/lib/datetime";
import { getFormatter } from "@/lib/datetime/server";
import { loadGameScopeInit } from "@/lib/site/discipline-server";
import { getPublicWorkspaces } from "@/lib/site/public-data";
import { cn } from "@/lib/utils";
import encounterService from "@/services/encounter.service";
import statisticsService from "@/services/statistics.service";
import tournamentService from "@/services/tournament.service";
import type { MapStatsResponse } from "@/types/statistics.types";
import type { Tournament } from "@/types/tournament.types";

import { NumbersReveal } from "./NumbersReveal";
import styles from "./PlatformNumbers.module.css";

const TITLE_ID = "home-numbers-title";

/** Four columns from `lg`, two from `sm`; `dense` lets a later tile fill the hole a left-out one leaves. */
const GRID_CLASS =
  "grid grid-flow-row-dense auto-rows-[minmax(11.875rem,auto)] grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4";
const BIG = "row-span-2 sm:col-span-2";
const WIDE = "sm:col-span-2";

const FIGURE_CLASS = "font-display font-extrabold tabular-nums text-[color:var(--aqt-fg)]";
const COUNT_CLASS = "block font-display text-title font-bold tabular-nums text-[color:var(--aqt-fg)]";
const SUB_CLASS = "text-body text-[color:var(--aqt-fg-muted)]";
const PERCENT = { style: "percent", maximumFractionDigits: 0 } as const;

/** The mode split's hues, in the order of the modes (most played first). */
const MODE_HUES = [
  "var(--aqt-teal)",
  "var(--aqt-amber)",
  "var(--aqt-violet)",
  "var(--aqt-blue)",
  "var(--aqt-rose)",
  "var(--aqt-emerald)"
];

const AVATARS = 6;
const DOT_PITCH = 9;
/** The bento is drawn once per page, so its one pattern can keep a fixed id. */
const DOT_PATTERN_ID = "home-numbers-dot";

type MapStat = MapStatsResponse["modes"][number]["maps"][number];

/**
 * The platform in numbers, across every community and all time, as a bento: the
 * audience a partner reaches and the scale an organizer joins. Each tile is a
 * figure with a small chart of its own; the reveal (`NumbersReveal`) plays once.
 * Absent when the totals cannot be read: a grid of dashes would argue against
 * the page. Every other read fails soft: its chart or fact is left out.
 */
export async function PlatformNumbers() {
  const [t, kpi, format, overall, workspaces, starts, split, overview] = await Promise.all([
    getTranslations("home.numbers"),
    getTranslations("site.kpi"),
    getFormatter(),
    statisticsService.getOverallStatistics({ skipWorkspace: true }).catch(() => null),
    getPublicWorkspaces().catch(() => null),
    tournamentService.getStartDates().catch(() => null),
    loadMapSplit().catch(() => null),
    encounterService.getOverview("", {}, "all").catch(() => null)
  ]);
  if (!overall) return null;

  // Zero is a count; only a figure the read does not carry (an older API) leaves its tile or fact out.
  const { players, champions, teams, days, tournaments, hours, maps, encounters } = overall;
  const years = starts ? perYear(starts) : [];
  const avgMap = typeof hours === "number" && maps > 0 ? Math.round((hours * 60) / maps) : null;
  const nonstop = typeof hours === "number" ? nonStop(hours) : null;

  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead title={t("title")} titleId={TITLE_ID} />
      <NumbersReveal as="dl" className={GRID_CLASS}>
        {typeof players === "number" ? (
          <Tile label={kpi("players")} className={cn(BIG, "justify-end")}>
            <dd
              data-count={players}
              className={cn(
                FIGURE_CLASS,
                "text-figure bg-[linear-gradient(180deg,var(--aqt-fg)_30%,var(--aqt-teal)_125%)] bg-clip-text text-transparent"
              )}
            >
              {format.number(players)}
            </dd>
            {typeof champions === "number" ? (
              <dd className={cn(SUB_CLASS, "sm:max-w-[48%]")}>
                {t.rich("champions", {
                  count: format.number(champions),
                  champions,
                  // "One player in N"; 0 leaves the clause out (no champion yet, or more titles than players).
                  every: champions > 0 ? Math.round(players / champions) : 0,
                  gold: (chunks) => (
                    <b data-count={champions} className="font-bold text-[color:var(--aqt-gold)]">
                      {chunks}
                    </b>
                  )
                })}
              </dd>
            ) : null}
            {typeof teams === "number" || typeof days === "number" ? (
              <dd className="mt-1.5 flex gap-[18px] border-t border-[color:var(--aqt-overlay-border)] pt-3.5 text-caption text-[color:var(--aqt-fg-dim)]">
                {typeof teams === "number" ? (
                  <span>
                    <b data-count={teams} className={cn(COUNT_CLASS, "mb-1")}>
                      {format.number(teams)}
                    </b>
                    {t("teams", { count: teams })}
                  </span>
                ) : null}
                {typeof days === "number" ? (
                  <span>
                    <b data-count={days} className={cn(COUNT_CLASS, "mb-1")}>
                      {format.number(days)}
                    </b>
                    {t("days", { count: days })}
                  </span>
                ) : null}
              </dd>
            ) : null}
            {players > 0 ? (
              <dd aria-hidden className="absolute inset-0 -z-10">
                <DotField total={players} gold={typeof champions === "number" ? champions : 0} />
              </dd>
            ) : null}
          </Tile>
        ) : null}

        {typeof tournaments === "number" ? (
          <Tile label={kpi("tournaments")} className={cn(WIDE, "justify-end")}>
            <Figure value={tournaments} format={format} />
            {years.length > 0 ? (
              <>
                <dd className={SUB_CLASS}>{t("since", { year: String(years[0][0]) })}</dd>
                <dd className="absolute inset-y-5 right-6 w-[min(55%,21rem)]">
                  <YearBars
                    years={years}
                    format={format}
                    label={t("perYear", {
                      list: years.map(([year, count]) => `${year}: ${format.number(count)}`).join(", ")
                    })}
                  />
                </dd>
              </>
            ) : null}
          </Tile>
        ) : null}

        {workspaces ? (
          <Tile label={kpi("communities")}>
            <Figure value={workspaces.length} format={format} />
            {workspaces.length > 0 ? (
              <dd aria-hidden className="mt-auto flex pl-0.5">
                {workspaces.slice(0, AVATARS).map((workspace) => (
                  // The stack spreads on hover: spacing inside the tile, never a scale.
                  <WorkspaceAvatar
                    key={workspace.id}
                    workspace={workspace}
                    size={42}
                    className="ring-2 ring-[color:var(--aqt-card)] transition-[margin] duration-400 ease-[cubic-bezier(0.2,0.8,0.2,1)] not-first:-ml-[11px] group-hover:not-first:ml-[5px]"
                  />
                ))}
              </dd>
            ) : null}
          </Tile>
        ) : null}

        {typeof hours === "number" ? (
          <Tile label={kpi("hours")}>
            <Figure value={hours} format={format} />
            {nonstop && nonstop.span > 0 ? (
              <>
                <dd className={SUB_CLASS}>{t(nonstop.unit, { count: nonstop.span })}</dd>
                <dd aria-hidden className="mt-auto grid grid-cols-[repeat(20,minmax(0,1fr))] gap-[3px]">
                  {Array.from({ length: nonstop.span }, (_, index) => (
                    <span
                      key={index}
                      className={cn(styles.cell, "aspect-square")}
                      style={{ "--i": index } as CSSProperties}
                    />
                  ))}
                </dd>
              </>
            ) : null}
          </Tile>
        ) : null}

        {typeof maps === "number" ? (
          <Tile label={kpi("maps")} className={WIDE}>
            <Figure value={maps} format={format} />
            {split ? (
              <>
                <dd aria-hidden className={cn(styles.sweep, "mt-auto flex h-2.5 max-w-[33.75rem] gap-[3px]")}>
                  {split.modes.map((mode, index) => (
                    <span
                      key={mode.name}
                      className="rounded-[3px] first:rounded-l-full last:rounded-r-full"
                      style={{ width: `${mode.share * 100}%`, background: MODE_HUES[index % MODE_HUES.length] }}
                    />
                  ))}
                </dd>
                <dd className="flex flex-wrap gap-x-3.5 gap-y-1.5 text-label text-[color:var(--aqt-fg-muted)]">
                  {split.modes.map((mode, index) => (
                    <span key={mode.name} className="inline-flex items-center gap-1.5">
                      <span
                        aria-hidden
                        className="size-2 rounded-[2px]"
                        style={{ background: MODE_HUES[index % MODE_HUES.length] }}
                      />
                      {mode.name}
                      <span className="tabular-nums text-[color:var(--aqt-fg-dim)]">
                        {format.number(mode.share, PERCENT)}
                      </span>
                    </span>
                  ))}
                </dd>
                <dd className="absolute right-[18px] top-[18px] text-label text-[color:var(--aqt-fg-muted)]">
                  {t.rich("topMap", {
                    game: split.game,
                    map: split.top.map.name,
                    games: format.number(split.top.games),
                    b: (chunks) => <b className="font-semibold text-[color:var(--aqt-fg)]">{chunks}</b>
                  })}
                </dd>
                {split.top.map.image_path ? (
                  <dd
                    aria-hidden
                    className="absolute inset-y-0 right-0 -z-10 w-[58%] opacity-40 transition-opacity duration-400 [mask-image:linear-gradient(90deg,transparent,black_65%)] group-hover:opacity-60"
                  >
                    <Image
                      src={split.top.map.image_path}
                      alt=""
                      fill
                      sizes="(min-width: 1024px) 22rem, 58vw"
                      className="object-cover"
                    />
                  </dd>
                ) : null}
              </>
            ) : null}
          </Tile>
        ) : null}

        {typeof encounters === "number" ? (
          <Tile label={kpi("encounters")} className={WIDE}>
            <Figure value={encounters} format={format} />
            {overview || avgMap !== null ? (
              <dd className="mt-auto grid grid-cols-3 gap-2.5">
                {overview ? (
                  <>
                    <Mini
                      icon={<Trophy aria-hidden className="size-4" />}
                      caption={t("finals", { count: overview.counts.finals })}
                    >
                      <b data-count={overview.counts.finals} className={COUNT_CLASS}>
                        {format.number(overview.counts.finals)}
                      </b>
                    </Mini>
                    <Mini
                      icon={<Zap aria-hidden className="size-4" />}
                      caption={t("upsets", { count: overview.counts.upsets })}
                      title={t("upsetHint")}
                    >
                      <b data-count={overview.counts.upsets} className={COUNT_CLASS}>
                        {format.number(overview.counts.upsets)}
                      </b>
                    </Mini>
                  </>
                ) : null}
                {avgMap !== null ? (
                  <Mini icon={<Clock aria-hidden className="size-4" />} caption={t("avgMap")}>
                    <b className={COUNT_CLASS}>
                      {format.number(avgMap, { style: "unit", unit: "minute", unitDisplay: "short" })}
                    </b>
                  </Mini>
                ) : null}
              </dd>
            ) : null}
          </Tile>
        ) : null}
      </NumbersReveal>
    </Section>
  );
}

/**
 * The maps tile's split, for one game: the first one installed, as the leaders' records pick it under all games.
 * Its modes by share of the games (under 1% and the unmoded left out), and its most played map.
 */
async function loadMapSplit() {
  const game = (await loadGameScopeInit()).disciplines?.find((entry) => entry.enabled);
  if (!game) return null;
  const { total_games: total, modes } = await statisticsService.getMaps(game.code, {
    skipWorkspace: true
  });
  const top = modes
    .flatMap((group) => group.maps)
    .reduce<MapStat | null>((best, row) => (best && best.games >= row.games ? best : row), null);
  if (total === 0 || !top) return null;
  return {
    game: game.name,
    top,
    modes: modes.flatMap(({ mode, games }) =>
      mode && games / total >= 0.01 ? [{ name: mode.name, share: games / total }] : []
    )
  };
}

/** Tournaments per start year, a pair each from the first year to this one (or the latest scheduled). */
function perYear(starts: readonly Tournament["start_date"][]): [number, number][] {
  const years = starts.map((start) => new Date(start).getUTCFullYear()).filter(Number.isFinite);
  if (years.length === 0) return [];
  const first = Math.min(...years);
  const last = Math.max(new Date().getUTCFullYear(), ...years);
  const counts = Array.from(
    { length: last - first + 1 },
    (_, index): [number, number] => [first + index, 0]
  );
  for (const year of years) counts[year - first][1] += 1;
  return counts;
}

/** A bordered tile: its label as the `dt`, then the caller's `dd`s (the figure first). */
function Tile({
  label,
  className,
  children
}: Readonly<{ label: string; className?: string; children: ReactNode }>) {
  return (
    <div className={cn(styles.tile, "group flex min-w-0 flex-col gap-2 px-6 py-5", className)}>
      <dt className={eyebrowClass("dim")}>{label}</dt>
      {children}
    </div>
  );
}

/** A tile's figure; `data-count` is what `NumbersReveal` counts up to. */
function Figure({ value, format }: Readonly<{ value: number; format: Formatter }>) {
  return (
    <dd data-count={value} className={cn(FIGURE_CLASS, "text-display")}>
      {format.number(value)}
    </dd>
  );
}

/**
 * The hours as time without a break, drawn a cell per unit lighting in turn: a cell per day reads to about 60,
 * past that the unit is a week.
 */
// ponytail: a cell per week fills the tile near 60 weeks (10k hours); a coarser unit then.
function nonStop(hours: number) {
  const days = Math.round(hours / 24);
  return days > 60
    ? ({ unit: "nonstopWeeks", span: Math.round(hours / 168) } as const)
    : ({ unit: "nonstopDays", span: days } as const);
}

/** A bar per year with its count over it, this year's teal. Read out as one list (`label`). */
function YearBars({
  years,
  format,
  label
}: Readonly<{ years: [number, number][]; format: Formatter; label: string }>) {
  const max = Math.max(1, ...years.map(([, count]) => count));
  return (
    <span
      role="img"
      aria-label={label}
      className="grid h-full auto-cols-fr grid-flow-col gap-[7px]"
    >
      {years.map(([year, count], index) => {
        const hot = index === years.length - 1;
        return (
          <span key={year} className="flex flex-col gap-[7px]">
            <span className="flex flex-1 items-end">
              <span
                className={cn(styles.bar, hot && styles.hot, "w-full")}
                style={{ "--h": `${(count / max) * 84}%`, "--i": index } as CSSProperties}
              >
                <span
                  className={cn(
                    "absolute bottom-full left-1/2 mb-[5px] -translate-x-1/2 text-label font-semibold tabular-nums",
                    hot ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-dim)]"
                  )}
                >
                  {format.number(count)}
                </span>
              </span>
            </span>
            <span className="text-center text-label text-[color:var(--aqt-fg-faint)]">
              {String(year).slice(2)}
            </span>
          </span>
        );
      })}
    </span>
  );
}

/**
 * One dot per player, the champions in gold, scattered by a fixed seed so every render draws the same field. The
 * grey dots are one SVG pattern (the full rows, then the partial last row); only the gold ones are circles.
 */
// ponytail: one dot per player stays legible to a few thousand; past that, a dot per N players.
function DotField({ total, gold }: Readonly<{ total: number; gold: number }>) {
  const cols = Math.ceil(Math.sqrt(total));
  const full = Math.floor(total / cols);
  const rest = total % cols;
  // mulberry32, seed 7: the same champions light up on every render.
  let seed = 7;
  const random = () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let x = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
  const golden = new Set<number>();
  while (golden.size < Math.min(gold, total)) golden.add(Math.floor(random() * total));
  const fill = `url(#${DOT_PATTERN_ID})`;

  return (
    <svg
      viewBox={`0 0 ${cols * DOT_PITCH} ${Math.ceil(total / cols) * DOT_PITCH}`}
      className={cn(
        styles.sweep,
        "absolute right-6 top-6 h-[45%] w-auto [mask-image:linear-gradient(90deg,transparent,black_58%)] sm:h-[calc(100%-3rem)]"
      )}
    >
      <defs>
        <pattern
          id={DOT_PATTERN_ID}
          width={DOT_PITCH}
          height={DOT_PITCH}
          patternUnits="userSpaceOnUse"
        >
          <circle
            cx={DOT_PITCH / 2}
            cy={DOT_PITCH / 2}
            r={2.4}
            className="fill-[color:color-mix(in_srgb,var(--aqt-fg-muted)_26%,transparent)]"
          />
        </pattern>
      </defs>
      <rect width={cols * DOT_PITCH} height={full * DOT_PITCH} fill={fill} />
      {rest > 0 ? (
        <rect y={full * DOT_PITCH} width={rest * DOT_PITCH} height={DOT_PITCH} fill={fill} />
      ) : null}
      <g className={cn(styles.gold, "fill-[color:var(--aqt-gold)]")}>
        {Array.from(golden, (index) => (
          <circle
            key={index}
            cx={((index % cols) + 0.5) * DOT_PITCH}
            cy={(Math.floor(index / cols) + 0.5) * DOT_PITCH}
            r={2.9}
          />
        ))}
      </g>
    </svg>
  );
}

/** One of the encounters tile's panels: an icon, a figure, its caption. */
function Mini({
  icon,
  caption,
  title,
  children
}: Readonly<{ icon: ReactNode; caption: string; title?: string; children: ReactNode }>) {
  return (
    <span
      title={title}
      className="flex min-w-0 flex-col gap-1 rounded-xl border border-[color:var(--aqt-overlay-border)] bg-[color:var(--aqt-overlay-2)] px-3 py-2.5 text-[color:var(--aqt-teal)]"
    >
      {icon}
      {children}
      <span className="text-label text-[color:var(--aqt-fg-dim)]">{caption}</span>
    </span>
  );
}

export function PlatformNumbersSkeleton() {
  return (
    <div aria-hidden>
      <Skeleton className="mb-4 h-8 w-72 max-w-full" />
      <div className={GRID_CLASS}>
        {[BIG, WIDE, "", "", WIDE, WIDE].map((span, index) => (
          <Skeleton key={index} className={cn("rounded-[var(--aqt-radius)]", span)} />
        ))}
      </div>
    </div>
  );
}
