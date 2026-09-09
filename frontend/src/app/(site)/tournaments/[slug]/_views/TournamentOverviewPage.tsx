"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  buildRoundGroups,
  orderEliminationRounds,
  stageFinalRounds,
  type RoundGroup
} from "@/components/bracket-view.helpers";
import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import TeamName from "@/components/TeamName";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { normalizePlayerRole, playerRoleSlotCode } from "@/lib/player-role";
import { ROSTER_SLOT_CODES, type RosterSlotCode } from "@/lib/roster-shape";
import { getStreamStatus, STREAM_STATUS_META } from "@/lib/stream-platform";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { cn } from "@/lib/utils";
import encounterService from "@/services/encounter.service";
import heroService from "@/services/hero.service";
import registrationService from "@/services/registration.service";
import teamService from "@/services/team.service";
import tournamentService from "@/services/tournament.service";
import type { Encounter } from "@/types/encounter.types";
import type { Registration } from "@/types/registration.types";
import type { StreamEntry } from "@/types/stream.types";
import type { Team } from "@/types/team.types";
import type { StageSummary, Standings, TournamentStatus } from "@/types/tournament.types";

import { MatchCard, isEncounterCompleted, isEncounterLive } from "../_components/MatchCard";
import { MatchRow } from "../_components/MatchRow";
import { PhaseTimeline } from "../_components/PhaseTimeline";
import { Podium, type PodiumTeam } from "../_components/Podium";
import { tournamentPlayersCount } from "../_components/TournamentClientLayout";
import {
  TournamentLinkChips,
  visibleTournamentLinks
} from "../_components/TournamentLinkChips";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentOverviewSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { useTournamentQuery } from "../_hooks/useTournamentClientData";
import { useTournamentStreamsQuery } from "../_hooks/useTournamentStreams";
import { getBracketRefetchInterval } from "../bracket/bracketData";
import { buildLiveTeamStreams } from "../bracket/bracketLiveStreams";
import styles from "../TournamentDetail.module.css";
import { getPublicPageQueryPresentation } from "./publicPageQueryPresentation";

// ---------------------------------------------------------------------------
// Which of the three compositions a tournament gets
// ---------------------------------------------------------------------------

export type OverviewVariant = "registration" | "live" | "completed";

/**
 * Exhaustive over `TournamentStatus` on purpose: a status added on the backend
 * then fails the build here instead of silently landing on a fallback branch.
 */
const VARIANT_BY_STATUS: Record<TournamentStatus, OverviewVariant> = {
  announcement: "registration",
  draft: "registration",
  registration: "registration",
  check_in: "registration",
  live: "live",
  playoffs: "live",
  completed: "completed",
  archived: "completed"
};

export function overviewVariant(status: TournamentStatus): OverviewVariant {
  return VARIANT_BY_STATUS[status];
}

/** Stage types with a bracket to draw, and with a standings table instead. */
const ELIMINATION_TYPES: Record<string, true> = {
  single_elimination: true,
  double_elimination: true
};
const GROUP_TYPES: Record<string, true> = { round_robin: true, swiss: true };

/**
 * How each stage type reads beside the organizer's own stage name. A registry
 * over the backend's vocabulary rather than a chain of ternaries — the reason
 * `CHIP_META` and `TOURNAMENT_STATUS_META` are registries — with existing keys,
 * so no new copy. `stage_type` is a free column, so an unlisted value renders
 * the name alone instead of a raw enum token.
 */
const STAGE_TYPE_LABEL: Record<string, "common.roundRobin" | "common.swiss" | "bracket.singleElimination" | "bracket.doubleElimination"> = {
  round_robin: "common.roundRobin",
  swiss: "common.swiss",
  single_elimination: "bracket.singleElimination",
  double_elimination: "bracket.doubleElimination"
};

/**
 * The stage the overview draws: the one being played now, and after the
 * tournament ends the one that decided it.
 *
 * Unpublished stages are skipped the way the bracket skips them
 * (`isStageVisibleToViewer`), unless nothing is published at all — an organizer
 * previewing their own tournament still sees which stage is meant.
 */
export function pickOverviewStage(
  stages: readonly StageSummary[],
  variant: OverviewVariant
): StageSummary | null {
  const ordered = [...stages].sort((left, right) => left.order - right.order);
  const visible = ordered.filter((stage) => stage.is_published || stage.is_completed);
  const pool = visible.length > 0 ? visible : ordered;
  if (pool.length === 0) return null;

  if (variant === "completed") {
    return (
      pool.filter((stage) => ELIMINATION_TYPES[stage.stage_type] === true).at(-1) ??
      pool.at(-1) ??
      null
    );
  }
  return (
    pool.find((stage) => stage.is_active) ??
    pool.find((stage) => !stage.is_completed) ??
    pool.at(-1) ??
    null
  );
}

/** The round the stage is on: the first with anything unfinished, else its last. */
export function currentRoundOf(groups: readonly RoundGroup[]): number | null {
  for (const group of groups) {
    if (group.matches.some((match) => !isEncounterCompleted(match))) return group.round;
  }
  return groups.at(-1)?.round ?? null;
}

/**
 * Up to four columns of the mini-bracket (§3 ⑥): the current round with a
 * neighbour on each side, plus the stage's decider when that window does not
 * already reach it — the wireframe's "R1 · R2 · LR3 · GRAND FINAL".
 */
export function pickRoundWindow(
  groups: readonly RoundGroup[],
  currentRound: number | null
): RoundGroup[] {
  if (groups.length <= 4) return [...groups];

  const index =
    currentRound === null ? -1 : groups.findIndex((group) => group.round === currentRound);
  const start = index < 0 ? groups.length - 3 : Math.max(0, Math.min(index - 1, groups.length - 3));
  const window = groups.slice(start, start + 3);
  const decider = groups[groups.length - 1];
  return window.includes(decider) ? window : [...window, decider];
}

/** The completed encounter that decided the bracket: highest positive round. */
export function findGrandFinal(
  encounters: readonly Encounter[],
  stageId: number
): Encounter | null {
  const played = encounters.filter(
    (encounter) =>
      encounter.stage_id === stageId && encounter.round > 0 && isEncounterCompleted(encounter)
  );
  return played.reduce<Encounter | null>(
    (best, encounter) => (best === null || encounter.round > best.round ? encounter : best),
    null
  );
}

/**
 * The lower-bracket final: the deepest negative round. Its loser is third in a
 * double elimination bracket (§5 of the plan's default decisions).
 */
export function findLowerFinal(
  encounters: readonly Encounter[],
  stageId: number
): Encounter | null {
  const played = encounters.filter(
    (encounter) =>
      encounter.stage_id === stageId && encounter.round < 0 && isEncounterCompleted(encounter)
  );
  return played.reduce<Encounter | null>(
    (best, encounter) => (best === null || encounter.round < best.round ? encounter : best),
    null
  );
}

function winnerSide(encounter: Encounter): "home" | "away" | null {
  const home = encounter.score?.home ?? 0;
  const away = encounter.score?.away ?? 0;
  if (home === away) return null;
  return home > away ? "home" : "away";
}

/** Registrations per role slot, counted from each entry's primary role. */
export function countRegistrationRoles(
  registrations: readonly Registration[]
): Record<RosterSlotCode, number> {
  const counts: Record<RosterSlotCode, number> = { tank: 0, dps: 0, support: 0, flex: 0 };
  for (const registration of registrations) {
    const roles = registration.roles ?? [];
    const primary = roles.find((role) => role.is_primary) ?? roles[0];
    if (!primary) continue;
    counts[playerRoleSlotCode(normalizePlayerRole(primary.role))] += 1;
  }
  return counts;
}

/**
 * Calendar days the tournament spans, inclusive. UTC getters on both ends so
 * the number is the same during SSR and after hydration.
 */
export function tournamentDaySpan(start: Date | string, end: Date | string): number | null {
  const from = new Date(start);
  const to = new Date(end);
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return null;
  const days =
    Math.floor(
      (Date.UTC(to.getUTCFullYear(), to.getUTCMonth(), to.getUTCDate()) -
        Date.UTC(from.getUTCFullYear(), from.getUTCMonth(), from.getUTCDate())) /
        86_400_000
    ) + 1;
  return days > 0 ? days : null;
}

/** The champion's roster as one line — names only, the `#1234` is noise here (§3C). */
function rosterBattletags(team: Team | null | undefined): string {
  const players = team?.players ?? [];
  return players
    .map((player) => player.name)
    .filter((name): name is string => typeof name === "string" && name.length > 0)
    .map((name) => name.split("#")[0])
    .join(" · ");
}

/**
 * The stage's standings split into the ladders they actually are.
 *
 * A group stage's `stage_item`s are independent tables, each ranking 1..N of
 * its own field. Merged into one list and sorted by `position` they interleave
 * into 1,1,2,2,… — a rank column that says nothing and rows that read as
 * unsorted. Same split key the bracket page builds its per-group panels on;
 * the label falls back to the team's group when `stage_item` was not expanded,
 * and to `null` (one unnamed ladder) when neither is there.
 */
export function splitStandingsByGroup(
  rows: readonly Standings[]
): { key: string; name: string | null; rows: Standings[] }[] {
  const groups = new Map<string, { key: string; name: string | null; rows: Standings[] }>();
  for (const row of rows) {
    const key = String(row.stage_item_id ?? "stage");
    const group = groups.get(key) ?? {
      key,
      name: row.stage_item?.name ?? row.team?.group?.name ?? null,
      rows: []
    };
    group.rows.push(row);
    groups.set(key, group);
  }
  return [...groups.values()]
    .sort((left, right) => (left.name ?? "").localeCompare(right.name ?? ""))
    .map((group) => ({
      ...group,
      rows: [...group.rows].sort((left, right) => left.position - right.position)
    }));
}

// ---------------------------------------------------------------------------
// Small shared surfaces
// ---------------------------------------------------------------------------

/**
 * One block of the overview: a card on the site's first-level surface with a
 * mono eyebrow (wireframes §11) — see `.block` in the module CSS for the
 * treatment and why it is framed.
 */
function OverviewCard({
  title,
  action,
  id,
  children
}: Readonly<{
  title?: string;
  action?: React.ReactNode;
  id?: string;
  children: React.ReactNode;
}>) {
  return (
    <section className={cn(styles.block, "scroll-mt-28")} id={id}>
      {title || action ? (
        <div className={styles.blockHead}>
          {title ? <h2 className={styles.blockTitle}>{title}</h2> : <span />}
          {action}
        </div>
      ) : null}
      {children}
    </section>
  );
}

function CardLink({ href, children }: Readonly<{ href: string; children: React.ReactNode }>) {
  return (
    <Link
      href={href}
      className="text-label uppercase tracking-label text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-teal)]"
    >
      {children}
    </Link>
  );
}

function OverviewStreamCard({
  official,
  href,
  action,
  viewers
}: Readonly<{
  official: StreamEntry;
  href: string;
  action: React.ReactNode;
  viewers: string | null;
}>) {
  const t = useTranslations();
  const status = getStreamStatus(official.live);
  const meta = STREAM_STATUS_META[status];

  return (
    <OverviewCard title={t("tournamentDetail.overview.stream.title")} action={action}>
      <Link
        href={href}
        className="group relative block overflow-hidden rounded-lg bg-[color:var(--aqt-overlay-2)] outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
      >
        {official.thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- remote poster from an arbitrary streaming host; not in `next.config` image domains.
          <img
            src={official.thumbnail_url}
            alt=""
            className="aspect-video w-full object-cover transition-[filter] duration-300 group-hover:brightness-110 motion-reduce:transition-none"
            loading="lazy"
          />
        ) : (
          <span aria-hidden className="block aspect-video w-full bg-[color:var(--aqt-overlay-3)]" />
        )}
        {meta.labelKey ? (
          <span className={`${meta.pillClassName} absolute left-3 top-3 z-[1]`}>
            {meta.hasDot ? <span aria-hidden className="dot" /> : null}
            {t(meta.labelKey)}
          </span>
        ) : null}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,transparent_42%,hsl(220_22%_4%/0.88))]"
        />
        <span className="absolute inset-x-0 bottom-0 flex flex-col gap-0.5 p-3">
          <span className="text-sm font-semibold text-[color:var(--aqt-fg)]">{official.channel}</span>
          {viewers ? (
            <span className="aqt-tnum text-label text-[color:var(--aqt-fg-muted)]">{viewers}</span>
          ) : null}
        </span>
      </Link>
    </OverviewCard>
  );
}

function StatTile({
  label,
  value,
  hint,
  accent
}: Readonly<{ label: string; value: string; hint?: string; accent?: string }>) {
  return (
    <div className={styles.figure}>
      <div className={cn(styles.figureLabel, "flex items-center gap-1.5")}>
        {accent ? (
          <span aria-hidden className="size-1.5 rounded-full" style={{ background: accent }} />
        ) : null}
        {label}
      </div>
      <div className={styles.figureValue}>
        {value}
        {hint ? <span className={styles.figureHint}>{hint}</span> : null}
      </div>
    </div>
  );
}

/** The site's role tints (`PlayerRoleIcon` uses the same tokens), keyed by slot code. */
const ROLE_TINT: Record<RosterSlotCode, string> = {
  tank: "var(--aqt-tank)",
  dps: "var(--aqt-damage)",
  support: "var(--aqt-support)",
  flex: "var(--aqt-flex)"
};

function KeyValue({ term, children }: Readonly<{ term: string; children: React.ReactNode }>) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-3">
      <dt className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)] sm:pt-0.5">
        {term}
      </dt>
      <dd className="min-w-0 text-ui text-[color:var(--aqt-fg-muted)]">{children}</dd>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------

type TournamentOverviewPageProps = {
  tournamentId: number;
  slug: string;
};

/**
 * The tournament's landing section — one component, three compositions keyed on
 * `status` (wireframes §3 A/B/C). The retired Schedule tab lives here as the
 * phase timeline (`#phases`); Maps is its own section.
 */
export default function TournamentOverviewPage({
  tournamentId,
  slug
}: Readonly<TournamentOverviewPageProps>) {
  const t = useTranslations();
  const format = useFormatter();
  const roundLabel = useBracketRoundLabel();
  // Null until hydration — recency text waits rather than disagree with SSR.
  const clockNow = useMinuteClock();

  const tournamentQuery = useTournamentQuery(slug);
  const tournament = tournamentQuery.data;
  const variant = tournament ? overviewVariant(tournament.status) : null;
  const workspaceId = tournament?.workspace_id;

  // Memoised for its identity, not its cost: `stageId`/`stageType` below are
  // read off this object and feed the `stageEncounters`/`roundGroups`
  // dependency arrays, and a value re-derived every render is one the compiler
  // has to treat as free to change underneath those memos.
  const stage = useMemo(
    () => (tournament && variant ? pickOverviewStage(tournament.stages, variant) : null),
    [tournament, variant]
  );
  const showsGroupTable =
    variant !== "registration" && stage !== null && GROUP_TYPES[stage.stage_type] === true;
  // A group-only tournament has no bracket to read third place off, so the
  // podium falls back to the standings (plan §5).
  const podiumNeedsStandings =
    variant === "completed" &&
    !(tournament?.stages ?? []).some((item) => ELIMINATION_TYPES[item.stage_type] === true);
  const needsStandings = showsGroupTable || podiumNeedsStandings;
  // Team registration counts teams, not players, so it never reads the roster.
  const needsRegistrations =
    variant === "registration" && tournament?.team_formation !== "registration";

  // Same key and fetcher as `TournamentParticipantsPage`, so the two sections
  // share one cache entry instead of each paying for the roster.
  const registrationsQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationsList(workspaceId ?? 0, tournamentId),
    queryFn: () => registrationService.listRegistrations(tournamentId),
    enabled: tournament !== undefined && needsRegistrations
  });

  // Same key as the bracket's own plan (`bracketData.createBracketQueryPlan`).
  const encountersQuery = useQuery({
    queryKey: tournamentQueryKeys.encounters(tournamentId, workspaceId),
    queryFn: () =>
      encounterService.getAll(1, "", tournamentId, -1, undefined, undefined, workspaceId),
    enabled: tournament !== undefined && variant !== "registration",
    refetchInterval: tournament ? getBracketRefetchInterval(tournament.status) : false,
    refetchIntervalInBackground: false
  });

  // Same key as `TournamentStandingsPage`.
  const standingsQuery = useQuery({
    queryKey: tournamentQueryKeys.standings(tournamentId, workspaceId),
    queryFn: () => tournamentService.getStandings(tournamentId, workspaceId ?? null),
    enabled: tournament !== undefined && needsStandings
  });

  // Same key as `TournamentTeamsPage` — the champion's battletags come off the
  // roster entity, which the encounters read does not carry.
  const teamsQuery = useQuery({
    queryKey: tournamentQueryKeys.teams(tournamentId, workspaceId),
    queryFn: () => teamService.getAll({ tournamentId, workspaceId }),
    enabled: tournament !== undefined && variant === "completed"
  });

  // Same key as `TournamentHeroPlaytimePage`.
  const heroesQuery = useQuery({
    queryKey: tournamentQueryKeys.heroPlaytime(tournamentId),
    queryFn: () => heroService.getHeroPlaytime(1, -1, "all", tournamentId, { workspaceId }),
    enabled: tournament !== undefined && variant === "completed"
  });

  const streamsQuery = useTournamentStreamsQuery(variant === "live" ? tournamentId : undefined);

  const encounters = encountersQuery.data ? encountersQuery.data.results : [];
  const registrations = registrationsQuery.data ?? [];
  const standings = standingsQuery.data ?? [];
  const teams = teamsQuery.data ? teamsQuery.data.results : [];

  const stageId = stage?.id ?? null;
  const stageEncounters = useMemo(
    () =>
      stageId === null ? [] : encounters.filter((encounter) => encounter.stage_id === stageId),
    [encounters, stageId]
  );
  // Play order (upper → lower → finals), so the window ends on the decider at
  // the right — `buildRoundGroups` interleaves by depth and would put the
  // grand final in the middle of the lower bracket.
  const stageType = stage?.stage_type;
  const roundGroups = useMemo(
    () =>
      stageType !== undefined && ELIMINATION_TYPES[stageType] === true
        ? orderEliminationRounds(stageEncounters, stageType).groups
        : buildRoundGroups(stageEncounters),
    [stageEncounters, stageType]
  );
  // Per stage, because "Latest results" spans stages: a group stage's highest
  // round is not a Grand Final, and naming it one would contradict the bracket.
  const finalRoundsByStage = useMemo(() => {
    const byStage: Record<number, number[]> = {};
    for (const item of tournament?.stages ?? []) {
      const rounds = encounters
        .filter((encounter) => encounter.stage_id === item.id)
        .map((encounter) => encounter.round);
      byStage[item.id] = stageFinalRounds(item.id, item.stage_type, rounds, encounters);
    }
    return byStage;
  }, [encounters, tournament?.stages]);
  const finalRounds = stageId === null ? [] : (finalRoundsByStage[stageId] ?? []);

  const liveTeamStreams = useMemo(
    () => buildLiveTeamStreams(streamsQuery.data),
    [streamsQuery.data]
  );

  const clock = (value: Date | string | null) => {
    if (value === null) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    // No explicit zone: next-intl's configured deployment zone is the same on
    // the server and the client, so the stamp survives hydration.
    return format.dateTime(date, { hour: "2-digit", minute: "2-digit" });
  };

  const encounterRound = (encounter: Encounter) =>
    roundLabel(
      encounter.round,
      encounter.stage_id === null ? [] : (finalRoundsByStage[encounter.stage_id] ?? [])
    );

  /** `STAGE · ROUND · BoN[ · HH:MM]`; the card's eyebrow is uppercased by CSS. */
  const eyebrowOf = (encounter: Encounter) => {
    const stageName =
      encounter.stage?.name ?? (encounter.stage_id === stageId ? stage?.name : undefined);
    const at = clock(encounter.scheduled_at);
    return [
      stageName,
      encounterRound(encounter),
      encounter.best_of ? `Bo${encounter.best_of}` : null,
      at
    ]
      .filter((part): part is string => typeof part === "string" && part.length > 0)
      .join(" · ");
  };

  const streamsCountOf = (encounter: Encounter) =>
    [encounter.home_team_id, encounter.away_team_id].filter((teamId) => liveTeamStreams.has(teamId))
      .length;

  const bracketHref = (encounter: Encounter) =>
    `/tournaments/${slug}/bracket?stage=${encounter.stage_id ?? stageId ?? ""}&match=${encounter.id}`;

  // The primary query per branch: what the page cannot be drawn without.
  const primary =
    variant === "registration" ? (needsRegistrations ? registrationsQuery : null) : encountersQuery;
  const presentation = getPublicPageQueryPresentation({
    // Nothing to wait for when the branch has no primary query: the overview
    // itself is already resolved by the time this runs.
    data: primary === null ? tournament : primary.data,
    itemCount:
      primary === null ? 1 : variant === "registration" ? registrations.length : encounters.length,
    isPending: primary?.isPending ?? false,
    isError: primary?.isError ?? false,
    isFetching: primary?.isFetching ?? false
  });

  if (!tournament || variant === null) {
    if (tournamentQuery.isError) {
      return (
        <TournamentPageState state="initial-error" onRetry={() => void tournamentQuery.refetch()} />
      );
    }
    return <TournamentOverviewSkeleton />;
  }

  if (presentation.initialState === "error") {
    return <TournamentPageState state="initial-error" onRetry={() => void primary?.refetch()} />;
  }
  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentOverviewSkeleton />;
  }

  const overviewHref = `/tournaments/${slug}`;
  const teamsCount = tournament.teams_count ?? 0;
  const playersCount = tournamentPlayersCount(tournament);

  // ---- shared right-column blocks -----------------------------------------
  const phasesCard = (
    <OverviewCard title={t("tournamentDetail.overview.phases.title")} id="phases">
      <PhaseTimeline tournament={tournament} orientation="vertical" />
    </OverviewCard>
  );

  // Slots as role glyphs, not "2 × Урон": the icon is the site's role
  // vocabulary everywhere else, and `RosterSlotGlyph` still announces the slot
  // name for screen readers.
  const rosterShape = tournament.roster_shape;
  const rosterSlots = rosterShape
    ? ROSTER_SLOT_CODES.filter((code) => (rosterShape.slots[code] ?? 0) > 0).map((code) => ({
        code,
        count: rosterShape.slots[code] as number
      }))
    : [];

  /**
   * ③ Format, team formation and the full description — what the header used to
   * carry as two pills and one clamped line.
   *
   * Present in EVERY branch, not only before the start: the header is now the
   * tournament's state and its actions, so this is the only place the
   * description is readable, and "what is this tournament" does not stop being
   * a question once the first match is played.
   */
  const formatCard = (
    <OverviewCard title={t("tournamentDetail.overview.format.title")}>
      <dl className="grid gap-2.5">
        {tournament.stages.length > 0 ? (
          /* The card's own heading already says "Format", and the derived label
             (`Groups → Playoff`) restated the stage names right beside it —
             "Groups → Playoff — Groups → Playoffs". The organizer's own stage
             names carry it, with each stage's type where the name does not. */
          <KeyValue term={t("common.stages")}>
            {[...tournament.stages]
              .sort((left, right) => left.order - right.order)
              .map((stage, index) => {
                const typeKey = STAGE_TYPE_LABEL[stage.stage_type];
                return (
                  <span key={stage.id}>
                    {index > 0 ? (
                      <span className="text-[color:var(--aqt-fg-faint)]">{" → "}</span>
                    ) : null}
                    {stage.name}
                    {typeKey ? (
                      <span className="text-[color:var(--aqt-fg-faint)]">
                        {" ("}
                        {t(typeKey).toLowerCase()}
                        {")"}
                      </span>
                    ) : null}
                  </span>
                );
              })}
          </KeyValue>
        ) : null}
        <KeyValue term={t("common.teamFormation")}>
          {t(
            `common.${(tournament.team_formation ?? "balancer") as "balancer" | "draft" | "registration"}`
          )}
          {rosterSlots.length > 0 ? (
            <span className="ml-2 inline-flex items-center gap-2 align-middle">
              {rosterSlots.map(({ code, count }) => (
                <span key={code} className="inline-flex items-center gap-1">
                  <RosterSlotGlyph code={code} size={14} />
                  <span className="aqt-tnum text-[color:var(--aqt-fg-faint)]">×{count}</span>
                </span>
              ))}
            </span>
          ) : null}
        </KeyValue>
        {tournament.description ? (
          <KeyValue term={t("tournamentDetail.overview.format.description")}>
            <span className="block whitespace-pre-line leading-relaxed">
              {tournament.description}
            </span>
          </KeyValue>
        ) : null}
      </dl>
    </OverviewCard>
  );

  /**
   * The organizer's Discord, rules and external bracket — moved out of the
   * header (see `TournamentLinkChips` for why) and always the LAST card of the
   * right column in all three branches. One predictable address beats a block
   * that migrates by phase.
   *
   * `null` when nothing renders: `visibleTournamentLinks` owns that judgement,
   * so a tournament whose only link is the official stream does not get a
   * heading over an empty row.
   */
  const linksCard =
    visibleTournamentLinks(tournament.links).length > 0 ? (
      <OverviewCard title={t("tournamentDetail.links.heading")}>
        <TournamentLinkChips links={tournament.links} />
      </OverviewCard>
    ) : null;

  // ---- the mini bracket / group table (§3 ⑥) -------------------------------

  const miniBracket =
    stage !== null && !showsGroupTable && roundGroups.length > 0 ? (
      <OverviewCard
        title={t("tournamentDetail.overview.bracketMini.title", { stage: stage.name })}
        action={
          <CardLink href={`${overviewHref}/bracket?stage=${stage.id}`}>
            {t("tournamentDetail.overview.bracketMini.open")}
          </CardLink>
        }
      >
        <div className="flex gap-2 overflow-x-auto pb-1">
          {pickRoundWindow(roundGroups, currentRoundOf(roundGroups)).map((group) => (
            <div className="min-w-[13rem] flex-1 space-y-1.5" key={group.round}>
              <div className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                {roundLabel(group.round, finalRounds)}
              </div>
              {group.matches.map((match) => {
                const encounter = stageEncounters.find((item) => item.id === match.id);
                if (!encounter) return null;
                return (
                  <MatchCard
                    key={encounter.id}
                    encounter={encounter}
                    eyebrow={eyebrowOf(encounter)}
                    href={bracketHref(encounter)}
                    size="sm"
                    streamsCount={streamsCountOf(encounter)}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </OverviewCard>
    ) : null;

  const stageStandings = stage ? standings.filter((row) => row.stage_id === stage.id) : [];
  const standingsGroups = splitStandingsByGroup(stageStandings);
  // One decimal everywhere as soon as any row carries a half point: a
  // right-aligned column of "4" beside "3.5" has no shared decimal to scan.
  const pointsHaveFraction = stageStandings.some((row) => !Number.isInteger(row.points));
  const formatPoints = (points: number) =>
    pointsHaveFraction ? points.toFixed(1) : String(points);

  const groupTable =
    showsGroupTable && stage !== null && stageStandings.length > 0 ? (
      <OverviewCard
        title={t("tournamentDetail.overview.groupTable.title", { stage: stage.name })}
        action={
          <CardLink href={`${overviewHref}/bracket?stage=${stage.id}&view=standings`}>
            {t("tournamentDetail.overview.groupTable.open")}
          </CardLink>
        }
      >
        {/* Two groups sit side by side rather than stacking: it halves the card
            and pulls the record back next to the name instead of stranding it
            against the far edge of a 900px row. */}
        <div className={cn("grid gap-x-8 gap-y-5", standingsGroups.length > 1 && "sm:grid-cols-2")}>
          {standingsGroups.map((group) => (
            <table className="w-full table-fixed text-sm" key={group.key}>
              <caption
                className={cn(
                  "text-left",
                  group.name === null
                    ? "sr-only"
                    : "pb-1.5 text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]"
                )}
              >
                {group.name === null
                  ? t("tournamentDetail.overview.groupTable.title", { stage: stage.name })
                  : `${t("common.group")} ${group.name}`}
              </caption>
              <thead>
                <tr className="border-b border-[color:var(--aqt-border)] text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                  <th scope="col" className="w-8 py-1.5 pr-2 text-left font-medium">
                    <span aria-hidden>{t("tournamentDetail.overview.groupTable.pos")}</span>
                    <span className="sr-only">
                      {t("tournamentDetail.overview.groupTable.posLabel")}
                    </span>
                  </th>
                  <th scope="col" className="py-1.5 pr-2 text-left font-medium">
                    {t("tournamentDetail.overview.groupTable.team")}
                  </th>
                  <th scope="col" className="w-20 py-1.5 pr-2 text-right font-medium">
                    {t("standings.colWDL")}
                  </th>
                  <th scope="col" className="w-12 py-1.5 text-right font-medium">
                    {t("tournamentDetail.overview.groupTable.points")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {group.rows.map((row) => (
                  <tr key={row.id}>
                    <td className="aqt-tnum py-1.5 pr-2 text-[color:var(--aqt-fg-muted)]">
                      {row.position}
                    </td>
                    <td className="py-1.5 pr-2">
                      <TeamName team={row.team ?? { name: t("common.tbd") }} size="xs" />
                    </td>
                    {/* W·D·L, not W–L: these stages draw, and a "3–0" printed
                        for a 3W-2D-0L run contradicts both the matches played
                        and the points beside it. */}
                    <td className="aqt-tnum py-1.5 pr-2 text-right">
                      {row.win}·{row.draw}·{row.lose}
                    </td>
                    <td className="aqt-tnum py-1.5 text-right font-semibold">
                      {formatPoints(row.points)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ))}
        </div>
      </OverviewCard>
    ) : null;

  // ---- A: registration (§3A) ----------------------------------------------

  if (variant === "registration") {
    const roleCounts = countRegistrationRoles(registrations);
    const submitted = [...registrations]
      .filter((registration) => registration.submitted_at !== null)
      .sort((left, right) => String(right.submitted_at).localeCompare(String(left.submitted_at)));
    const latest = submitted
      .slice(0, 3)
      .map((registration) => registration.battle_tag)
      .filter((tag): tag is string => typeof tag === "string" && tag.length > 0);
    const latestAt = submitted[0]?.submitted_at ?? null;
    const latestAgo =
      latestAt !== null && clockNow !== null
        ? format.relativeTime(new Date(latestAt), clockNow)
        : null;
    const isTeamRegistration = tournament.team_formation === "registration";
    // Both aside cards are optional, and an aside column holding nothing reads
    // as a broken layout rather than as restraint.
    const hasAside = linksCard !== null;
    // The share of each role in the field — what a draft/balancer organizer
    // reads ("tanks are short"). Role tints, the same dots on the figures above.
    const roleShares = ROSTER_SLOT_CODES.filter((code) => roleCounts[code] > 0);
    const roleTotal = roleShares.reduce((sum, code) => sum + roleCounts[code], 0);

    const content = (
      <section className={styles.publicDataPage} aria-label={t("common.overview")}>
        {presentation.showUpdating ? <UpdatingBadge /> : null}

        {/* ① The phase timeline IS the page before the tournament starts. */}
        <OverviewCard id="phases">
          <PhaseTimeline tournament={tournament} orientation="horizontal" />
        </OverviewCard>

        <div className={cn("grid gap-4", hasAside && "lg:grid-cols-[6fr_4fr]")}>
          <div className={cn("grid content-start gap-4", !hasAside && "lg:grid-cols-2")}>
            {/* ② "Tanks are short" is what a draft/balancer tournament is read
                for; a team-registration one counts teams instead. */}
            <OverviewCard
              title={t("tournamentDetail.overview.registration.title")}
              action={
                <CardLink href={`${overviewHref}/participants`}>
                  {t("tournamentDetail.overview.registration.all")}
                </CardLink>
              }
            >
              {isTeamRegistration ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  <StatTile
                    label={t("tournamentDetail.overview.registration.teams")}
                    value={String(teamsCount)}
                  />
                  <StatTile
                    label={t("tournamentDetail.overview.registration.total")}
                    value={String(tournament.registrations_count ?? 0)}
                  />
                </div>
              ) : (
                <>
                  <div className="grid gap-2 sm:grid-cols-4">
                    <StatTile
                      label={t("tournamentDetail.overview.registration.total")}
                      value={String(tournament.registrations_count ?? registrations.length)}
                    />
                    {roleShares.map((code) => (
                      <StatTile
                        key={code}
                        label={t(`common.roles.${code}`)}
                        value={String(roleCounts[code])}
                        accent={ROLE_TINT[code]}
                      />
                    ))}
                  </div>
                  {roleShares.length > 1 && roleTotal > 0 ? (
                    <div aria-hidden className="mt-3 flex h-1.5 gap-px overflow-hidden rounded-sm">
                      {roleShares.map((code) => (
                        <span
                          key={code}
                          style={{
                            width: `${(roleCounts[code] / roleTotal) * 100}%`,
                            background: ROLE_TINT[code]
                          }}
                        />
                      ))}
                    </div>
                  ) : null}
                  {latest.length > 0 ? (
                    <p className="mt-2 truncate text-caption text-[color:var(--aqt-fg-faint)]">
                      {t("tournamentDetail.overview.registration.latest")}: {latest.join(" · ")}
                      {latestAgo ? ` · ${latestAgo}` : null}
                    </p>
                  ) : null}
                </>
              )}
            </OverviewCard>

            {formatCard}
          </div>

          {/* Organizer links — the same tail the other two branches end on. */}
          {hasAside ? (
            <div className="grid content-start gap-4">
              {linksCard}
            </div>
          ) : null}
        </div>
      </section>
    );

    if (presentation.showRefreshError) {
      return (
        <TournamentPageState
          state="refresh-error"
          onRetry={() => void primary?.refetch()}
          isUpdating={primary?.isFetching ?? false}
        >
          {content}
        </TournamentPageState>
      );
    }
    return content;
  }

  // ---- B / C: after the first whistle -------------------------------------

  const liveEncounters = encounters.filter(isEncounterLive);
  const upcoming = encounters
    .filter((encounter) => {
      if (isEncounterCompleted(encounter) || isEncounterLive(encounter)) return false;
      if (encounter.scheduled_at === null) return false;
      const at = new Date(encounter.scheduled_at).getTime();
      if (!Number.isFinite(at)) return false;
      // `clockNow` is null until hydration. Reading the wall clock here instead
      // would be a different instant on the server than in the browser, so the
      // pre-hydration pass keeps every scheduled match and the first client
      // render drops the ones that have already come round.
      return clockNow === null || at > clockNow;
    })
    .sort(
      (left, right) =>
        new Date(left.scheduled_at ?? 0).getTime() - new Date(right.scheduled_at ?? 0).getTime()
    )
    .slice(0, 4);
  const recent = encounters
    .filter(isEncounterCompleted)
    .sort((left, right) => {
      const leftAt = new Date(left.ended_at ?? left.scheduled_at ?? left.created_at).getTime();
      const rightAt = new Date(right.ended_at ?? right.scheduled_at ?? right.created_at).getTime();
      if (leftAt !== rightAt) return rightAt - leftAt;
      return right.id - left.id;
    })
    .slice(0, 4);
  // Drawn, but nobody has given it a time yet: a generated round sits here
  // until it is scheduled or played. Without this rung the overview claims
  // nothing is published while the bracket page shows a full grid.
  const pending = encounters
    .filter((encounter) => !isEncounterCompleted(encounter) && !isEncounterLive(encounter))
    .sort((left, right) => {
      if (left.round !== right.round) return Math.abs(left.round) - Math.abs(right.round);
      return left.id - right.id;
    })
    .slice(0, 4);

  const matchRows = (rows: Encounter[], withTime: boolean) => (
    <div>
      {rows.map((encounter) => (
        <MatchRow
          key={encounter.id}
          encounter={encounter}
          leading={(withTime ? clock(encounter.scheduled_at) : null) ?? encounterRound(encounter)}
          trailing={encounter.best_of ? `Bo${encounter.best_of}` : undefined}
          bracketHref={bracketHref(encounter)}
          returnTo={overviewHref}
        />
      ))}
    </div>
  );

  // ⑤ Live first and framed; nothing live falls back to the schedule, and
  // without a schedule to the last results.
  const nowBlock =
    liveEncounters.length > 0 ? (
      <OverviewCard
        title={t("tournamentDetail.overview.live.title")}
        action={
          <CardLink href={`${overviewHref}/matches`}>
            {t("tournamentDetail.overview.live.all")}
          </CardLink>
        }
      >
        <div className="grid gap-2 sm:grid-cols-2">
          {liveEncounters.map((encounter) => (
            <MatchCard
              key={encounter.id}
              encounter={encounter}
              eyebrow={eyebrowOf(encounter)}
              href={bracketHref(encounter)}
              streamsCount={streamsCountOf(encounter)}
            />
          ))}
        </div>
      </OverviewCard>
    ) : upcoming.length > 0 ? (
      <OverviewCard
        title={t("tournamentDetail.overview.upcoming.title")}
        action={
          <CardLink href={`${overviewHref}/matches?view=time`}>
            {t("tournamentDetail.overview.live.all")}
          </CardLink>
        }
      >
        {matchRows(upcoming, true)}
      </OverviewCard>
    ) : recent.length > 0 ? (
      <OverviewCard
        title={t("tournamentDetail.overview.recent.title")}
        action={
          <CardLink href={`${overviewHref}/matches`}>
            {t("tournamentDetail.overview.live.all")}
          </CardLink>
        }
      >
        {matchRows(recent, false)}
      </OverviewCard>
    ) : pending.length > 0 ? (
      <OverviewCard
        title={t("tournamentDetail.overview.upcoming.title")}
        action={
          <CardLink href={`${overviewHref}/matches`}>
            {t("tournamentDetail.overview.live.all")}
          </CardLink>
        }
      >
        {matchRows(pending, false)}
      </OverviewCard>
    ) : (
      <TournamentPageState
        state="empty"
        title={t("tournamentDetail.overview.empty.title")}
        description={t("tournamentDetail.overview.empty.description")}
      />
    );

  if (variant === "live") {
    const officialStreams = streamsQuery.data?.official ?? [];
    const official = officialStreams[0];
    const participantsOnAir = streamsQuery.data?.participants.length ?? 0;
    const playedCount = encounters.filter(isEncounterCompleted).length;

    const content = (
      <section className={styles.publicDataPage} aria-label={t("common.overview")}>
        {presentation.showUpdating ? <UpdatingBadge /> : null}
        <div className="grid gap-4 lg:grid-cols-[7fr_3fr]">
          <div className="grid content-start gap-4">
            {nowBlock}
            {miniBracket}
            {groupTable}
          </div>
          <div className="grid content-start gap-4">
            {/* ⑦ The same timeline, second orientation. */}
            {phasesCard}
            {/* Poster only, no autoplay: the broadcast dock already owns the
                player, and a second one would fight it for the audio. */}
            {official ? (
              <OverviewStreamCard
                official={official}
                href={`${overviewHref}/stream`}
                action={
                  <CardLink href={`${overviewHref}/stream`}>
                    {participantsOnAir > 0
                      ? t("tournamentDetail.overview.stream.participants", {
                          count: participantsOnAir
                        })
                      : t("tournamentDetail.overview.stream.open")}
                  </CardLink>
                }
                viewers={
                  official.viewer_count != null
                    ? t("tournamentDetail.overview.stream.viewers", {
                        count: format.number(official.viewer_count)
                      })
                    : null
                }
              />
            ) : null}
            <OverviewCard title={t("tournamentDetail.overview.numbers.title")}>
              <div className="grid gap-2 sm:grid-cols-2">
                <StatTile
                  label={t("tournamentDetail.overview.numbers.teams")}
                  value={String(teamsCount)}
                />
                <StatTile
                  label={t("tournamentDetail.overview.numbers.played")}
                  value={`${playedCount}/${encounters.length}`}
                />
              </div>
            </OverviewCard>
            {/* Reference tail, identical in the completed branch: what this
                tournament is, then where the organizer's channels are. */}
            {formatCard}
            {linksCard}
          </div>
        </div>
      </section>
    );

    if (presentation.showRefreshError) {
      return (
        <TournamentPageState
          state="refresh-error"
          onRetry={() => void encountersQuery.refetch()}
          isUpdating={encountersQuery.isFetching}
        >
          {content}
        </TournamentPageState>
      );
    }
    return content;
  }

  // ---- C: completed (§3C) -------------------------------------------------

  const teamById = new Map(teams.map((team) => [team.id, team]));
  // Only a bracket crowns a champion by its last match. A group stage's final
  // round is just another round, so its podium comes off the standings below.
  const grandFinal =
    stageId === null || stage === null || ELIMINATION_TYPES[stage.stage_type] !== true
      ? null
      : findGrandFinal(encounters, stageId);
  const lowerFinal =
    stageId === null || stage?.stage_type !== "double_elimination"
      ? null
      : findLowerFinal(encounters, stageId);

  const podiumTeam = (team: Team | null | undefined, note: string | null): PodiumTeam | null => {
    if (!team) return null;
    return { id: team.id, name: team.name, image_url: team.image_url, note };
  };

  let podium: { first: PodiumTeam; second: PodiumTeam; third: PodiumTeam | null } | null = null;

  if (grandFinal) {
    const side = winnerSide(grandFinal);
    const championSide = side ?? "home";
    const champion = championSide === "home" ? grandFinal.home_team : grandFinal.away_team;
    const runnerUp = championSide === "home" ? grandFinal.away_team : grandFinal.home_team;
    const championScore = championSide === "home" ? grandFinal.score.home : grandFinal.score.away;
    const runnerUpScore = championSide === "home" ? grandFinal.score.away : grandFinal.score.home;
    // The roster comes off the teams read; the encounters read carries no players.
    const roster = rosterBattletags(teamById.get(champion?.id ?? -1) ?? champion);
    const first = podiumTeam(champion, roster.length > 0 ? roster : null);
    const second = podiumTeam(
      runnerUp,
      t("tournamentDetail.overview.result.finalScore", {
        score: `${runnerUpScore}–${championScore}`
      })
    );
    let third: PodiumTeam | null = null;
    if (lowerFinal) {
      const lowerSide = winnerSide(lowerFinal);
      const eliminated = lowerSide === "home" ? lowerFinal.away_team : lowerFinal.home_team;
      third = podiumTeam(
        eliminated,
        t("tournamentDetail.overview.result.exitedIn", {
          round: roundLabel(lowerFinal.round, finalRounds)
        })
      );
    }
    if (first && second) podium = { first, second, third };
  } else if (podiumNeedsStandings) {
    // Group-only: third by standings (plan §5).
    const ranked = [...standings].sort(
      (left, right) => left.overall_position - right.overall_position
    );
    const note = (row: Standings | undefined, roster: boolean) => {
      if (!row) return null;
      if (roster) {
        const tags = rosterBattletags(teamById.get(row.team_id) ?? row.team);
        if (tags.length > 0) return tags;
      }
      return t("tournamentDetail.overview.result.record", { wins: row.win, losses: row.lose });
    };
    const first = podiumTeam(
      teamById.get(ranked[0]?.team_id ?? -1) ?? ranked[0]?.team,
      note(ranked[0], true)
    );
    const second = podiumTeam(
      teamById.get(ranked[1]?.team_id ?? -1) ?? ranked[1]?.team,
      note(ranked[1], false)
    );
    const third = podiumTeam(
      teamById.get(ranked[2]?.team_id ?? -1) ?? ranked[2]?.team,
      note(ranked[2], false)
    );
    if (first && second) podium = { first, second, third };
  }

  const topHeroes = heroesQuery.data
    ? [...heroesQuery.data.results]
        .sort((left, right) => right.playtime - left.playtime)
        .slice(0, 5)
    : [];
  const days = tournamentDaySpan(tournament.start_date, tournament.end_date);

  const completedContent = (
    <section className={styles.publicDataPage} aria-label={t("common.overview")}>
      {presentation.showUpdating ? <UpdatingBadge /> : null}
      <div className="grid gap-4 lg:grid-cols-[7fr_3fr]">
        <div className="grid content-start gap-4">
          {/* ⑧ A finished tournament opens on its result, not on the bracket
              corner the final happens to sit in. */}
          {podium ? (
            <OverviewCard title={t("tournamentDetail.overview.result.title")}>
              <Podium first={podium.first} second={podium.second} third={podium.third} />
            </OverviewCard>
          ) : null}
          {miniBracket}
          {groupTable}
          {podium === null && miniBracket === null && groupTable === null ? nowBlock : null}
        </div>
        <div className="grid content-start gap-4">
          {topHeroes.length > 0 ? (
            <OverviewCard
              title={t("tournamentDetail.overview.heroes.title")}
              action={
                <CardLink href={`${overviewHref}/stats?tab=heroes`}>
                  {t("tournamentDetail.overview.heroes.all")}
                </CardLink>
              }
            >
              <ol className="grid gap-1.5">
                {topHeroes.map((entry, index) => {
                  const share = Math.min(100, Math.max(0, entry.playtime * 100));
                  const widest = Math.min(100, Math.max(0, topHeroes[0].playtime * 100));
                  return (
                    <li
                      className="grid grid-cols-[1rem_1.5rem_minmax(0,1fr)_auto_2.75rem] items-center gap-2"
                      key={entry.hero.id}
                    >
                      <span
                        className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]"
                        aria-hidden
                      >
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <Avatar className="size-6 border-none bg-transparent">
                        {entry.hero.image_path ? (
                          <AvatarImage
                            src={entry.hero.image_path}
                            alt={entry.hero.name}
                            className="object-contain"
                          />
                        ) : null}
                        <AvatarFallback className="bg-transparent" />
                      </Avatar>
                      <span className="min-w-0 truncate text-caption" title={entry.hero.name}>
                        {entry.hero.name}
                      </span>
                      <span
                        aria-hidden
                        className="hidden h-1.5 w-16 overflow-hidden rounded-sm bg-[color:var(--aqt-border)] sm:block"
                      >
                        <span
                          className="block h-full bg-[color:var(--aqt-fg-muted)]"
                          style={{ width: `${widest > 0 ? (share / widest) * 100 : 0}%` }}
                        />
                      </span>
                      <span className="aqt-tnum text-right text-label text-[color:var(--aqt-fg-muted)]">
                        {format.number(entry.playtime, {
                          style: "percent",
                          maximumFractionDigits: 1
                        })}
                      </span>
                    </li>
                  );
                })}
              </ol>
            </OverviewCard>
          ) : null}
          <OverviewCard title={t("tournamentDetail.overview.numbers.title")}>
            <div className="grid gap-2 sm:grid-cols-2">
              <StatTile
                label={t("tournamentDetail.overview.numbers.teams")}
                value={String(teamsCount)}
              />
              <StatTile
                label={t("tournamentDetail.overview.numbers.players")}
                value={String(playersCount)}
              />
              <StatTile
                label={t("tournamentDetail.overview.numbers.matches")}
                value={String(encounters.length)}
              />
              {days !== null ? (
                <StatTile
                  label={t("tournamentDetail.overview.numbers.days")}
                  value={String(days)}
                />
              ) : null}
            </div>
          </OverviewCard>
          {formatCard}
          {linksCard}
        </div>
      </div>
    </section>
  );

  if (presentation.showRefreshError) {
    return (
      <TournamentPageState
        state="refresh-error"
        onRetry={() => void encountersQuery.refetch()}
        isUpdating={encountersQuery.isFetching}
      >
        {completedContent}
      </TournamentPageState>
    );
  }
  return completedContent;
}
