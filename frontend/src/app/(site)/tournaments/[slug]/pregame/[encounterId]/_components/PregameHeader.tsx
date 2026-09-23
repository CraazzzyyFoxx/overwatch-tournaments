"use client";

import Link from "next/link";
import {
  ArrowLeft,
  Ban,
  Check,
  CircleCheck,
  CircleSlash,
  Flag,
  Hourglass,
  MapPin
} from "lucide-react";
import { useTranslations } from "next-intl";

import { TeamLogo, type TeamNameInput } from "@/components/TeamName";
import { PickBanItemThumb } from "@/components/pick-ban/PickBanItemThumb";
import type { PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import { cn } from "@/lib/utils";
import type { Encounter } from "@/types/encounter.types";
import type { PickBanSession } from "@/types/tournament.types";

/** One step of the round the room is on. `map`/`hero` mirror `PickBanKind`. */
export type PregamePhase = "map" | "hero" | "report" | "done";

export interface PregamePhaseStatus {
  phase: PregamePhase;
  done: boolean;
}

/** Where one map of the series stands, in the loop's own terms. */
type PregameSeriesMapState =
  /** Played and reconciled — it has a confirmed score. */
  | "played"
  /** The map the loop is waiting on right now: played or being played, unreported. */
  | "awaiting"
  /** A later map of the series; not reached yet, nothing to show. */
  | "upcoming";

/** One map of this series, in play order. */
export interface PregameSeriesMap {
  /** Which map of the series this is, 1-based. */
  round: number;
  name: string;
  item: PickBanItemLike | undefined;
  /** The confirmed score. Only ever set when `state` is `"played"`. */
  score: { home: number; away: number } | null;
  state: PregameSeriesMapState;
}

interface PregameHeaderProps {
  encounter: Encounter;
  /** Null before both captains are ready -- no session exists yet (see `PregameReadiness`). */
  session: PickBanSession | null;
  activePhase: PregamePhase;
  /**
   * The steps of ONE round of the series, in loop order: the map is picked, its
   * heroes are banned, it is played and reported, and that result opens the
   * next map. Only the steps that apply to this encounter are listed.
   */
  phases: PregamePhaseStatus[];
  /** Which map of the series the room is on, 1-based; null before the first. */
  round: number | null;
  /** Maps this series has settled, oldest first. Empty before the first pick. */
  series: PregameSeriesMap[];
  /**
   * The live series score: wins over the confirmed games, counted by the
   * backend. Null for a room whose payload carries no games (hero-only, or an
   * older read), where the encounter's own score is the best available.
   */
  seriesScore?: { home: number; away: number } | null;
  /** The finalized official score, set only once the encounter is finalized. */
  official?: { home_score: number; away_score: number } | null;
  /** Where the back arrow leads: the page the room was opened from. */
  returnTo: string;
}

/** Accent per session state — carried by an icon, not a labelled pill. */
const STATUS_COLOR: Record<PickBanSession["status"], string> = {
  active: "var(--aqt-teal)",
  completed: "var(--aqt-support)",
  cancelled: "var(--aqt-amber)"
};

/** The glyph that stands for each step of the loop once it is not yet done. */
const PHASE_ICON: Record<PregamePhase, typeof MapPin> = {
  map: MapPin,
  hero: Ban,
  report: Flag,
  done: Check
};

/**
 * Shared header content for the unified pre-game room. Renders as bare
 * content (no `Card` of its own) so the caller can embed it as the top of
 * whichever card currently anchors the room -- the Map/Hero Pool card once a
 * session exists, a loading card while one is pending.
 *
 * Everything below the title bar is diagrammatic rather than prose: a
 * scoreboard (crest, seed, series score against the Bo-N target), a connected
 * rail of the round's steps, and a filmstrip of the maps already settled. The
 * three replace what used to be a row of same-weight badges and a "name ·
 * seed · 1st" text line, where nothing carried the one number a captain
 * actually opens this room for -- where the series stands.
 *
 * Renders with `session=null` while the room is open but waiting on captain
 * readiness -- `PregameReadiness` then takes the pool's place BELOW this header
 * rather than covering it, which is why the header must stay legible in that
 * state: every session-derived piece (status chip, seeds, opener marker) is
 * skipped, and the matchup plus the series standing carry the room on their own.
 * The turn timer lives in `PickBanCommandBar`, which only ever
 * renders once a session exists. The "who goes first" banner lives in
 * `PickBanStepTimeline` instead, next to the steps it explains.
 */
export function PregameHeader({
  encounter,
  session,
  activePhase,
  phases,
  round,
  series,
  seriesScore = null,
  official = null,
  returnTo
}: Readonly<PregameHeaderProps>) {
  const t = useTranslations("pickBan.room");
  const homeTeam = encounter.home_team ?? null;
  const awayTeam = encounter.away_team ?? null;
  const bestOf = encounter.best_of ?? null;
  // Wins over the confirmed games, not the encounter's column: the encounter
  // only carries a score once it is finalized, and until then the games ARE
  // the series standing.
  const score = seriesScore ?? encounter.score ?? null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link
          href={returnTo}
          aria-label={t("back")}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:bg-[color:var(--aqt-card-2)] hover:text-[color:var(--aqt-fg)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <h1 className="font-onest text-xl font-semibold tracking-[-0.01em]">{t("title")}</h1>
        {session != null ? <StatusMark status={session.status} /> : null}
        {round != null ? (
          <span className="ml-auto text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
            {t("round.label", { n: round })}
            {bestOf != null ? ` / ${t("board.bestOf", { n: bestOf })}` : ""}
          </span>
        ) : null}
      </div>

      <Scoreboard
        homeName={homeTeam?.name ?? t("side.home")}
        awayName={awayTeam?.name ?? t("side.away")}
        homeTeam={homeTeam}
        awayTeam={awayTeam}
        homeSeed={session?.home_seed ?? null}
        awaySeed={session?.away_seed ?? null}
        firstSide={session?.first_side ?? null}
        score={score}
        official={official}
        bestOf={bestOf}
      />

      {phases.length > 1 ? <PhaseRail phases={phases} activePhase={activePhase} /> : null}

      {series.length > 0 ? <SeriesStrip series={series} /> : null}
    </div>
  );
}

/**
 * Session state as one mark rather than a labelled pill: a pulsing dot while a
 * session is live, a check once it is done, a slash once it is cancelled. The
 * words move to `title`/screen-reader text — the colour and glyph already say
 * it, and a third uppercase pill next to the room title said it twice.
 */
function StatusMark({ status }: Readonly<{ status: PickBanSession["status"] }>) {
  const t = useTranslations("pickBan.room");
  const label = t(`statusChip.${status}`);
  const color = STATUS_COLOR[status];
  const Icon = status === "completed" ? CircleCheck : CircleSlash;

  return (
    <span className="inline-flex shrink-0 items-center" title={label}>
      <span className="sr-only">{label}</span>
      {status === "active" ? (
        <span
          aria-hidden
          className="h-2 w-2 animate-pulse rounded-full motion-reduce:animate-none"
          style={{ background: color, boxShadow: `0 0 8px ${color}` }}
        />
      ) : (
        <Icon aria-hidden className="h-4 w-4" style={{ color }} />
      )}
    </span>
  );
}

/**
 * The matchup as a broadcast scoreboard: each side's logo and seed flanking
 * the series score, with a dot per map of the Bo-N underneath so "2–1 of a
 * Bo5" reads as position in the series and not just two digits.
 */
function Scoreboard({
  homeName,
  awayName,
  homeTeam,
  awayTeam,
  homeSeed,
  awaySeed,
  firstSide,
  score,
  official,
  bestOf
}: Readonly<{
  homeName: string;
  awayName: string;
  homeTeam: TeamNameInput | null | undefined;
  awayTeam: TeamNameInput | null | undefined;
  homeSeed: number | null;
  awaySeed: number | null;
  firstSide: "home" | "away" | null;
  score: { home: number; away: number } | null;
  official: { home_score: number; away_score: number } | null;
  bestOf: number | null;
}>) {
  const t = useTranslations("pickBan.room");
  const homeScore = score?.home ?? 0;
  const awayScore = score?.away ?? 0;
  // Bo1 has nothing to track across maps, so the pip row is skipped there.
  const toWin = bestOf != null && bestOf > 1 ? Math.floor(bestOf / 2) + 1 : null;

  return (
    <div
      aria-label={t("board.label")}
      // Stacked below `sm` -- three columns on a phone truncate both team names
      // to three characters, which is worse than losing the side-by-side read.
      // From `sm` up: `minmax(0,…)` tracks, never plain `1fr`, since a grid item
      // defaults to `min-width:auto` and would refuse to shrink under a long
      // name, riding over the score.
      className="flex flex-col gap-2.5 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card-2)]/40 px-3 py-3 sm:grid sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-center sm:gap-6 sm:px-5"
    >
      <TeamSide
        name={homeName}
        team={homeTeam}
        seed={homeSeed}
        accentVar="--aqt-teal"
        opens={firstSide === "home"}
        align="start"
      />

      <div className="flex flex-col items-center gap-1.5">
        <div className="flex items-baseline gap-2 font-onest text-[clamp(1.6rem,3.4vw,2.35rem)] font-semibold leading-none tabular-nums">
          {/* The leader takes its side's accent; a tie leaves both plain so the
              colour never claims an advantage that is not there. */}
          <span
            style={{
              color:
                homeScore > awayScore
                  ? "var(--aqt-teal)"
                  : homeScore < awayScore
                    ? "var(--aqt-fg-muted)"
                    : "var(--aqt-fg)"
            }}
          >
            {homeScore}
          </span>
          <span aria-hidden className="text-[0.6em] text-[color:var(--aqt-fg-faint)]">
            :
          </span>
          <span
            style={{
              color:
                awayScore > homeScore
                  ? "var(--aqt-rose)"
                  : awayScore < homeScore
                    ? "var(--aqt-fg-muted)"
                    : "var(--aqt-fg)"
            }}
          >
            {awayScore}
          </span>
        </div>
        {toWin != null ? (
          <>
            <SeriesPips homeScore={homeScore} awayScore={awayScore} toWin={toWin} />
            <span className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
              {t("board.toWin", { n: toWin })}
            </span>
          </>
        ) : (
          <span className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
            {t("board.score")}
          </span>
        )}
        {official != null ? (
          <span
            data-official-score
            className="text-label uppercase tracking-label text-[color:var(--aqt-support)]"
          >
            {t("board.official", {
              home: official.home_score,
              away: official.away_score
            })}
          </span>
        ) : null}
      </div>

      <TeamSide
        name={awayName}
        team={awayTeam}
        seed={awaySeed}
        accentVar="--aqt-rose"
        opens={firstSide === "away"}
        align="end"
      />
    </div>
  );
}

function TeamSide({
  name,
  team,
  seed,
  accentVar,
  opens,
  align
}: Readonly<{
  name: string;
  team: TeamNameInput | null | undefined;
  seed: number | null;
  accentVar: "--aqt-teal" | "--aqt-rose";
  opens: boolean;
  align: "start" | "end";
}>) {
  const t = useTranslations("pickBan.room");

  return (
    <div
      className={cn(
        "flex min-w-0 items-center gap-2.5",
        align === "end" ? "flex-row-reverse" : null
      )}
    >
      <TeamLogo team={team} size="md" />
      {/* `flex-1`, never `items-end`: a non-stretch cross alignment sizes the
          name to its own min-content, so `truncate` stops clamping and a long
          team name rides over the score. The block stretches; `text-right` and
          the reversed rows do the mirroring instead. */}
      <div
        className={cn(
          "flex min-w-0 flex-1 flex-col gap-0.5",
          align === "end" ? "text-right" : null
        )}
      >
        <span
          title={name}
          className="min-w-0 truncate font-onest text-base font-semibold leading-tight sm:text-lg"
          style={{ color: `var(${accentVar})` }}
        >
          {name}
        </span>
        <span
          className={cn(
            "flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]",
            align === "end" ? "flex-row-reverse" : null
          )}
        >
          <span className="whitespace-nowrap">
            {t("board.seed")} {seed != null ? seed : t("board.seedNone")}
          </span>
          {opens ? (
            // Bare glyph, no pill: the flag next to the seed already reads as
            // "this side opens", and the words live in `title`/screen-reader
            // text instead of a fourth tinted box in the header.
            <span
              className="inline-flex shrink-0 items-center text-[color:var(--aqt-teal)]"
              title={t("board.opens")}
            >
              <span className="sr-only">{t("board.opens")}</span>
              <Flag className="h-3 w-3" aria-hidden />
            </span>
          ) : null}
        </span>
      </div>
    </div>
  );
}

/**
 * One pip per map of the Bo-N: won by home (teal, from the left), won by away
 * (rose, from the right), still to play (hollow). Purely decorative — the
 * digits above already carry the score for a screen reader.
 */
function SeriesPips({
  homeScore,
  awayScore,
  toWin
}: Readonly<{
  homeScore: number;
  awayScore: number;
  toWin: number;
}>) {
  return (
    <span aria-hidden className="flex items-center gap-1">
      {Array.from({ length: toWin }, (_, index) => (
        <span
          key={`home-${index}`}
          className="h-1.5 w-3.5 rounded-full"
          style={{ background: index < homeScore ? "var(--aqt-teal)" : "var(--aqt-border-2)" }}
        />
      ))}
      <span className="mx-0.5 h-2.5 w-px bg-[color:var(--aqt-border-3)]" />
      {Array.from({ length: toWin }, (_, index) => (
        <span
          key={`away-${index}`}
          className="h-1.5 w-3.5 rounded-full"
          style={{
            background: toWin - 1 - index < awayScore ? "var(--aqt-rose)" : "var(--aqt-border-2)"
          }}
        />
      ))}
    </span>
  );
}

/**
 * The round's steps as a rail of bare icon nodes — map pin, ban, flag — joined
 * by a connector filled up to the live step. Every node used to be a labelled
 * pill, which put three same-weight boxes next to the three of the filmstrip
 * and one more at the title; the glyph plus a filled/hollow/dashed ring says
 * the same thing, and ONE line under the rail names the step that is live.
 * Every node keeps its full name in `title` and screen-reader text.
 */
function PhaseRail({
  phases,
  activePhase
}: Readonly<{
  phases: PregamePhaseStatus[];
  activePhase: PregamePhase;
}>) {
  const t = useTranslations("pickBan.room");
  const activeEntry = phases.find((entry) => entry.phase === activePhase) ?? null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      <ol aria-label={t("phase.rail")} className="flex items-center">
        {phases.map((entry, index) => {
          const active = entry.phase === activePhase;
          const Icon = entry.done ? Check : PHASE_ICON[entry.phase];
          const name = t(`phase.${entry.phase}`);
          const state = active
            ? t("phase.current")
            : entry.done
              ? t("phase.done")
              : t("phase.next");

          return (
            <li key={entry.phase} className="flex items-center">
              {index > 0 ? (
                <span
                  aria-hidden
                  className={cn(
                    "h-px w-5 shrink-0 sm:w-8",
                    entry.done || active
                      ? "bg-[color:var(--aqt-teal)]/50"
                      : "bg-[color:var(--aqt-border-2)]"
                  )}
                />
              ) : null}
              <span
                aria-current={active ? "step" : undefined}
                title={`${name} — ${state}`}
                className={cn(
                  "grid h-7 w-7 shrink-0 place-items-center rounded-full border transition-colors",
                  active
                    ? "border-[color:var(--aqt-teal)] bg-[color:var(--aqt-teal)]/12 text-[color:var(--aqt-teal)]"
                    : entry.done
                      ? "border-[color:var(--aqt-support)]/45 text-[color:var(--aqt-support)]"
                      : "border-dashed border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-faint)]"
                )}
              >
                <span className="sr-only">{`${name} — ${state}`}</span>
                <Icon aria-hidden className="h-3.5 w-3.5" />
              </span>
            </li>
          );
        })}
      </ol>
      {activeEntry != null ? (
        <span
          aria-hidden
          className="text-label uppercase tracking-label text-[color:var(--aqt-fg-muted)]"
        >
          <span className="text-[color:var(--aqt-teal)]">{t(`phase.${activeEntry.phase}`)}</span>
          {` · ${t("phase.current")}`}
        </span>
      ) : null}
    </div>
  );
}

/**
 * Every map of this series as a filmstrip of bare stills, in play order: the
 * ordinal rides the art as a corner chip, the name captions it, and a settled
 * map's confirmed score sits under it. No card around each entry — the still IS
 * the token, and boxing it turned the series into another row of chips
 * competing with the phase rail above.
 *
 * The three states read differently on purpose, because collapsing them to two
 * is what made an unreached map look finished:
 *
 * - `played`   — greyed art, confirmed score under it.
 * - `awaiting` — full colour, teal ring, hourglass over the art, NO score. It
 *                is the map being played/reported right now, so any number
 *                here would contradict the report panel below.
 * - `upcoming` — dimmed art, no overlay, no score: a map of the series the
 *                loop has not reached.
 */
function SeriesStrip({ series }: Readonly<{ series: PregameSeriesMap[] }>) {
  const t = useTranslations("pickBan.room");

  return (
    <ol aria-label={t("series.label")} className="flex flex-wrap items-start gap-4">
      {series.map((map) => {
        const awaiting = map.state === "awaiting";
        const stateLabel = awaiting
          ? t("series.awaiting")
          : map.state === "upcoming"
            ? t("series.upcoming")
            : null;
        return (
          <li key={map.round} className="flex w-[7.5rem] flex-col items-center gap-1.5">
            {/* Ring on the wrapper, not the thumb: the map thumb already carries
                an inset hairline ring, and `ring-inset` has no counter-utility
                for `twMerge` to strip. */}
            <span
              className={cn(
                // `rounded-md` to match the thumb's own radius: the ring is
                // offset, so a rounder wrapper reads as a second, wrong corner.
                "relative inline-block rounded-md",
                awaiting
                  ? "ring-2 ring-[color:var(--aqt-teal)] ring-offset-2 ring-offset-[color:var(--aqt-card)]"
                  : null
              )}
            >
              <PickBanItemThumb
                kind="map"
                item={map.item}
                name={map.name}
                // Big enough to recognise the art at a glance. At the old 40px
                // every still was a smear of skybox, so the filmstrip read as
                // decoration and the caption did all the work — which is
                // backwards for a strip whose whole point is the map.
                size={72}
                // Only an unreached map is dimmed. A played one keeps its colour:
                // `muted` is the pool's "banned" treatment (45% + grayscale) and
                // a settled map is not a rejected one.
                muted={map.state === "upcoming"}
              />
              <span
                aria-hidden
                className="absolute -left-1.5 -top-1.5 grid h-5 min-w-5 place-items-center rounded-full bg-[color:var(--aqt-card)] px-1 text-label font-bold leading-none text-[color:var(--aqt-fg-muted)] ring-1 ring-[color:var(--aqt-border-2)]"
              >
                {map.round}
              </span>
              {awaiting ? (
                <span
                  aria-hidden
                  className="absolute inset-0 grid place-items-center rounded-md bg-[color:var(--aqt-card)]/55"
                >
                  <Hourglass className="h-5 w-5 text-[color:var(--aqt-teal)]" />
                </span>
              ) : null}
            </span>
            <span className="sr-only">
              {t("round.label", { n: map.round })}
              {stateLabel != null ? ` — ${stateLabel}` : ""}
            </span>
            {/* Two lines, not one: "Watchpoint: Gibraltar" truncated to
                "Watchpoint: …" at a single line of this width, which named
                nothing. The fixed height keeps every column's score aligned. */}
            <span
              title={map.name}
              className="line-clamp-2 h-[2.2rem] w-full text-center text-label font-medium leading-tight"
            >
              {map.name}
            </span>
            {/* Digits belong to a settled map only. The other two states say
                where they stand with the ring/hourglass and the dimming — a
                caption here wrapped to two lines and knocked every column out
                of alignment. */}
            {map.score != null ? (
              <span className="font-onest text-sm font-semibold tabular-nums">
                <span style={{ color: "var(--aqt-teal)" }}>{map.score.home}</span>
                <span className="text-[color:var(--aqt-fg-faint)]">:</span>
                <span style={{ color: "var(--aqt-rose)" }}>{map.score.away}</span>
              </span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
