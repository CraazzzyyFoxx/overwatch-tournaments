"use client";

import { usePathname } from "next/navigation";
import { queryOptions, useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { CalendarClock, ListOrdered } from "lucide-react";

import {
  buildRoundGroups,
  getDoubleEliminationFinalRounds,
  orderEliminationRounds,
  type RoundGroup
} from "@/components/bracket-view.helpers";
import { FilterChip } from "@/components/ui/filter-chip";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { useBracketRoundLabel, type BracketRoundLabelFormatter } from "@/hooks/useBracketRoundLabel";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { useQueryParams } from "@/hooks/useQueryParams";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { areStreamsVisible } from "@/lib/tournament-status";
import encounterService from "@/services/encounter.service";
import type { Encounter } from "@/types/encounter.types";
import type { StageType, Tournament } from "@/types/tournament.types";

import styles from "../TournamentDetail.module.css";
import { isEncounterCompleted, isEncounterLive, MatchCard } from "../_components/MatchCard";
import { MatchRow } from "../_components/MatchRow";
import { SectionToolbar } from "../_components/SectionToolbar";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentMatchesSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { readViewParam, ViewSegment } from "../_components/ViewSegment";
import { useTournamentQuery } from "../_hooks/useTournamentClientData";
import { useTournamentStreamsQuery } from "../_hooks/useTournamentStreams";
import { buildLiveTeamStreams } from "../bracket/bracketLiveStreams";
import { getPublicPageQueryPresentation } from "./publicPageQueryPresentation";

const MATCHES_VIEWS = ["round", "time"] as const;
type MatchesView = (typeof MATCHES_VIEWS)[number];

/** Stage types whose rounds are named and numbered by the bracket rather than by group. */
const IS_ELIMINATION: Record<string, true> = {
  single_elimination: true,
  double_elimination: true
};

const HEADING_CLASS =
  "aqt-tnum mb-1 mt-5 text-label uppercase tracking-[.06em] text-[color:var(--aqt-fg-faint)]";

/**
 * Every encounter of the tournament, with the maps of each series.
 *
 * Deliberately NOT the bracket's cache entry
 * (`tournamentQueryKeys.encounters(id, workspaceId)`): the bracket asks for no
 * `matches` entity, and a shared key would let whichever screen mounted first
 * decide whether the row expansion has any maps to show. The `"maps"` marker in
 * the key keeps the two payloads apart; the shared prefix keeps realtime
 * invalidation (`tournament.encounters`) reaching both.
 *
 * Exported so the statistics section can count played maps out of the same
 * entry instead of fetching every encounter a second time.
 */
export function tournamentEncountersQueryOptions(
  tournament: Pick<Tournament, "id" | "workspace_id">
) {
  return queryOptions({
    queryKey: [
      ...tournamentQueryKeys.encounters(tournament.id, tournament.workspace_id),
      "maps"
    ] as const,
    queryFn: () =>
      encounterService.getAll(
        1,
        "",
        tournament.id,
        -1,
        undefined,
        undefined,
        tournament.workspace_id,
        {
          entities: [
            "tournament",
            "stage",
            "stage_item",
            "home_team",
            "away_team",
            // The row expansion is the series' maps with score, length and
            // mode; the nested relations only serialise when named.
            "matches",
            "matches.map",
            "matches.map.gamemode"
          ]
        }
      )
  });
}

function toDate(value: Date | string | null | undefined): Date | null {
  if (value == null) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** When a match happens, as the time view understands it: the plan first, then the record. */
function encounterInstant(encounter: Encounter): Date | null {
  return toDate(encounter.scheduled_at) ?? toDate(encounter.ended_at);
}

/** Local calendar day, so two matches an hour apart across midnight land on different days. */
function dayKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
}

/** A stage chip's URL value. `null` is a real bucket (a scrim-shaped encounter), not "all". */
function stageKey(stageId: number | null): string {
  return stageId === null ? "none" : String(stageId);
}

type StageMeta = {
  id: number | null;
  name: string;
  order: number;
  type: StageType | undefined;
};

/**
 * The stages that actually carry encounters, last stage first.
 *
 * `tournament.stages` is the source of names and order; a `stage_id` the
 * overview does not carry (a stage created after this page's tournament read)
 * still gets a bucket from the encounter's own `stage` relation, so no match
 * disappears from the chips.
 */
function collectStages(encounters: Encounter[], tournament: Tournament): StageMeta[] {
  const byId = new Map<number | null, StageMeta>();
  for (const encounter of encounters) {
    if (byId.has(encounter.stage_id)) continue;
    const summary =
      tournament.stages.find((stage) => stage.id === encounter.stage_id) ?? encounter.stage ?? null;
    byId.set(encounter.stage_id, {
      id: encounter.stage_id,
      name: summary?.name ?? "",
      order: summary?.order ?? -1,
      type: summary?.stage_type
    });
  }
  return [...byId.values()].sort((left, right) => right.order - left.order);
}

type MatchListRow = {
  encounter: Encounter;
  leading: string;
  trailing?: string;
};

type MatchBlock = {
  key: string;
  /** Mono heading, already joined with " · ". */
  heading: string;
  rows: MatchListRow[];
};

/**
 * One stage's rounds in reading order — final first — with the leading and
 * trailing mono cells of every row.
 *
 * Elimination stages come from `orderEliminationRounds` reversed: the
 * bracket's own match numbering is the only thing that knows the lower final
 * (round -4) is played before the grand final (round 3).
 */
function buildStageBlocks(
  stage: StageMeta,
  encounters: Encounter[],
  roundLabel: BracketRoundLabelFormatter,
  countLabel: (count: number) => string
): MatchBlock[] {
  const isElimination = IS_ELIMINATION[stage.type ?? ""] === true;
  const byId = new Map(encounters.map((encounter) => [encounter.id, encounter]));

  let groups: RoundGroup[];
  let finalRoundList: number[] = [];
  let matchNumbers = new Map<number, number>();

  if (isElimination) {
    const order = orderEliminationRounds(encounters, stage.type);
    groups = [...order.groups].reverse();
    finalRoundList = order.finalRounds;
    matchNumbers = order.matchNumbers;
  } else {
    groups = buildRoundGroups(encounters).sort((left, right) => right.round - left.round);
  }

  return groups.map((group) => {
    const rows: MatchListRow[] = [];
    for (const match of group.matches) {
      const encounter = byId.get(match.id);
      if (!encounter) continue;
      const bo = `Bo${encounter.best_of}`;
      if (isElimination) {
        const number = matchNumbers.get(encounter.id);
        // The group heading already names the round, so a trailing cell would
        // only repeat it — wireframe §7: playoff rows carry no trailing text.
        rows.push({ encounter, leading: number == null ? bo : `M${number} · ${bo}` });
        continue;
      }
      // Wireframe §7 ⑥: the group letter leads, the format trails. The round is
      // in the heading and the group is already the leading cell, so the
      // trailing cell says only what neither of them does.
      rows.push({ encounter, leading: encounter.stage_item?.name ?? bo, trailing: bo });
    }

    return {
      key: `${stageKey(stage.id)}:${group.round}`,
      heading: [
        stage.name,
        roundLabel(group.round, finalRoundList),
        rows.length > 1 ? countLabel(rows.length) : null
      ]
        .filter(Boolean)
        .join(" · "),
      rows
    };
  });
}

type DatedEncounter = { encounter: Encounter; at: Date };

type TimeSections = {
  live: Encounter[];
  /** Day blocks in reading order: today's remaining matches, later days, then played days. */
  days: MatchBlock[];
};

/**
 * The time view's sections: what is on air, what is still to come, then the
 * record by day.
 *
 * Note §7 ④ asks for the stage name in the day heading "from `phase_schedule`
 * when the day falls inside a phase". `phase_schedule` carries lifecycle phases
 * (registration / check-in / draft / live), never stage names — so the stage
 * comes from the day's own encounters when they unanimously share one, and the
 * phase is the fallback for a day whose matches carry no stage at all.
 *
 * The wireframe shows only "later today" ahead of the played days. Days further
 * out get their own section here rather than being dropped: a schedule
 * published a week ahead is the very data this view exists for.
 */
function buildTimeSections(
  encounters: Encounter[],
  now: Date,
  labels: {
    day: (date: Date) => string;
    time: (date: Date) => string;
    laterToday: string;
    unscheduled: string;
    phase: (date: Date) => string | null;
    trailing: (encounter: Encounter) => string | undefined;
    count: (count: number) => string;
  }
): TimeSections {
  const live: Encounter[] = [];
  const upcoming = new Map<string, DatedEncounter[]>();
  const past = new Map<string, DatedEncounter[]>();
  const undated: Encounter[] = [];
  const today = dayKey(now);

  for (const encounter of encounters) {
    if (isEncounterLive(encounter)) {
      live.push(encounter);
      continue;
    }
    const at = encounterInstant(encounter);
    if (at === null) {
      undated.push(encounter);
      continue;
    }
    const ahead = !isEncounterCompleted(encounter) && at.getTime() > now.getTime();
    const bucket = ahead ? upcoming : past;
    const key = dayKey(at);
    const existing = bucket.get(key);
    if (existing) existing.push({ encounter, at });
    else bucket.set(key, [{ encounter, at }]);
  }

  const toBlock = (key: string, dated: DatedEncounter[], ascending: boolean): MatchBlock => {
    const ordered = [...dated].sort((left, right) =>
      ascending ? left.at.getTime() - right.at.getTime() : right.at.getTime() - left.at.getTime()
    );
    const stageIds = new Set(ordered.map((row) => row.encounter.stage_id));
    const unanimousStage =
      stageIds.size === 1 ? ordered[0].encounter.stage?.name ?? null : null;
    const date = ordered[0].at;
    return {
      key,
      heading: [
        key === today && ordered.some((row) => !isEncounterCompleted(row.encounter))
          ? `${labels.laterToday} · ${labels.day(date)}`
          : labels.day(date),
        unanimousStage ?? labels.phase(date),
        ordered.length > 1 ? labels.count(ordered.length) : null
      ]
        .filter(Boolean)
        .join(" · "),
      rows: ordered.map((row) => ({
        encounter: row.encounter,
        leading: labels.time(row.at),
        trailing: labels.trailing(row.encounter)
      }))
    };
  };

  const days: MatchBlock[] = [
    ...[...upcoming.entries()]
      .sort((left, right) => left[1][0].at.getTime() - right[1][0].at.getTime())
      .map(([key, dated]) => toBlock(key, dated, true)),
    ...[...past.entries()]
      .sort((left, right) => right[1][0].at.getTime() - left[1][0].at.getTime())
      .map(([key, dated]) => toBlock(key, dated, false))
  ];

  if (undated.length > 0) {
    days.push({
      key: "undated",
      heading: [labels.unscheduled, labels.count(undated.length)].join(" · "),
      rows: undated.map((encounter) => ({
        encounter,
        leading: "—",
        trailing: labels.trailing(encounter)
      }))
    });
  }

  return { live, days };
}

interface TournamentEncountersPageProps {
  tournamentId: number;
  slug: string;
  /** Fixed clock for deterministic tests; the minute clock otherwise. */
  now?: number;
}

/**
 * The tournament's matches as two views of one list: by round (the bracket's
 * order, final first) and by time (on air, still to come, then the record by
 * day). The flat 90-row table this replaced grouped nothing and carried a
 * closeness bar and a TBD column that answered no question a reader had.
 */
const TournamentEncountersPage = ({ tournamentId, slug, now }: TournamentEncountersPageProps) => {
  const t = useTranslations();
  const format = useFormatter();
  const pathname = usePathname();
  const roundLabel = useBracketRoundLabel();
  const { searchParams, setParams } = useQueryParams();
  const clock = useMinuteClock();

  // Keyed by `slug`, not `tournamentId`: TournamentClientLayout's overview
  // query uses the same ref, so this reads its cache entry instead of
  // triggering a second fetch under a different key.
  const tournamentQuery = useTournamentQuery(slug);
  const tournament = tournamentQuery.data;

  const encountersQuery = useQuery({
    ...tournamentEncountersQueryOptions({
      id: tournamentId,
      workspace_id: tournament?.workspace_id ?? 0
    }),
    enabled: tournament !== undefined
  });
  const streamsQuery = useTournamentStreamsQuery(
    tournament && areStreamsVisible(tournament.status) ? tournamentId : undefined
  );

  const encounters = encountersQuery.data?.results ?? [];
  const presentation = getPublicPageQueryPresentation({
    data: encountersQuery.data,
    itemCount: encounters.length,
    isPending: encountersQuery.isPending,
    isError: encountersQuery.isError,
    isFetching: encountersQuery.isFetching
  });

  const stageParam = searchParams?.get("stage") ?? null;
  const teamParam = Number.parseInt(searchParams?.get("team") ?? "", 10);
  const mapParam = Number.parseInt(searchParams?.get("map") ?? "", 10);
  const teamFilter = Number.isSafeInteger(teamParam) ? teamParam : null;
  const mapFilter = Number.isSafeInteger(mapParam) ? mapParam : null;

  // The `time` segment exists only once the organizer has scheduled something,
  // so every tournament predating match scheduling keeps a single view (§7 ①).
  const hasSchedule = encounters.some((encounter) => encounter.scheduled_at != null);
  const requestedView = readViewParam<MatchesView>(searchParams, "view", MATCHES_VIEWS, "round");
  const view: MatchesView = hasSchedule ? requestedView : "round";

  const entityFiltered = encounters.filter((encounter) => {
    if (
      teamFilter !== null &&
      encounter.home_team_id !== teamFilter &&
      encounter.away_team_id !== teamFilter
    ) {
      return false;
    }
    if (
      mapFilter !== null &&
      !(encounter.matches ?? []).some((match) => match.map_id === mapFilter)
    ) {
      return false;
    }
    return true;
  });

  const stages = tournament ? collectStages(entityFiltered, tournament) : [];
  const stageFilter =
    stageParam !== null && stages.some((stage) => stageKey(stage.id) === stageParam)
      ? stageParam
      : null;
  const rows =
    stageFilter === null
      ? entityFiltered
      : entityFiltered.filter((encounter) => stageKey(encounter.stage_id) === stageFilter);

  const teamName =
    teamFilter === null
      ? null
      : encounters
          .map((encounter) =>
            encounter.home_team_id === teamFilter
              ? encounter.home_team?.name
              : encounter.away_team_id === teamFilter
                ? encounter.away_team?.name
                : null
          )
          .find(Boolean) ?? null;
  /** Every team with a match, once, by name — the picker's options. */
  const teamOptions = (() => {
    const byId: Record<number, string> = {};
    for (const encounter of encounters) {
      if (encounter.home_team) byId[encounter.home_team_id] = encounter.home_team.name;
      if (encounter.away_team) byId[encounter.away_team_id] = encounter.away_team.name;
    }
    return Object.entries(byId)
      .map(([id, name]) => ({ id: Number(id), name }))
      .sort((left, right) => left.name.localeCompare(right.name));
  })();
  const mapName =
    mapFilter === null
      ? null
      : encounters
          .flatMap((encounter) => encounter.matches ?? [])
          .find((match) => match.map_id === mapFilter)?.map?.name ?? null;

  const countLabel = (count: number) => t("tournamentDetail.matches.matchCount", { count });
  const groupWord = t("common.group");
  const liveTeamStreams = buildLiveTeamStreams(streamsQuery.data);

  /**
   * The trailing mono cell in the time view. The day heading names no round
   * there, so the row carries the round itself — plus the group for a
   * round-robin or swiss stage, where the round alone does not place the match.
   */
  const timeTrailing = (encounter: Encounter) => {
    const stage = tournament?.stages.find((item) => item.id === encounter.stage_id);
    const type = stage?.stage_type ?? encounter.stage?.stage_type;
    const bo = `Bo${encounter.best_of}`;
    const name = encounter.stage_item?.name;
    if (IS_ELIMINATION[type ?? ""] === true) {
      const finals =
        type === "double_elimination"
          ? [
              ...getDoubleEliminationFinalRounds(
                encounters.filter((row) => row.stage_id === encounter.stage_id)
              )
            ].sort((left, right) => left - right)
          : [];
      return `${roundLabel(encounter.round, finals)} · ${bo}`;
    }
    return [
      roundLabel(encounter.round, []),
      name ? (name.length <= 2 ? `${groupWord} ${name}` : name) : null,
      bo
    ]
      .filter(Boolean)
      .join(" · ");
  };

  const roundBlocks =
    view === "round" && tournament
      ? collectStages(rows, tournament).flatMap((stage) =>
          buildStageBlocks(
            stage,
            rows.filter((encounter) => encounter.stage_id === stage.id),
            roundLabel,
            countLabel
          )
        )
      : [];

  const nowMs = now ?? clock;
  const timeSections =
    view === "time" && nowMs !== null
      ? buildTimeSections(rows, new Date(nowMs), {
          day: (date) =>
            format.dateTime(date, { weekday: "short", day: "numeric", month: "short" }),
          time: (date) => format.dateTime(date, { hour: "2-digit", minute: "2-digit" }),
          laterToday: t("tournamentDetail.matches.laterToday"),
          unscheduled: t("tournamentDetail.matches.unscheduled"),
          phase: (date) => {
            const dayStart = new Date(date);
            dayStart.setHours(0, 0, 0, 0);
            const dayEnd = new Date(date);
            dayEnd.setHours(23, 59, 59, 999);
            const phase = tournament?.phase_schedule.find((entry) => {
              const starts = toDate(entry.starts_at);
              const ends = toDate(entry.ends_at);
              return starts !== null && starts <= dayEnd && (ends === null || ends >= dayStart);
            });
            return phase ? t(`common.statusBadge.${phase.status}`) : null;
          },
          trailing: timeTrailing,
          count: countLabel
        })
      : null;

  if (!tournament) {
    if (tournamentQuery.isError) {
      return (
        <TournamentPageState state="initial-error" onRetry={() => void tournamentQuery.refetch()} />
      );
    }
    return <TournamentMatchesSkeleton />;
  }

  if (presentation.initialState === "error") {
    return (
      <TournamentPageState state="initial-error" onRetry={() => void encountersQuery.refetch()} />
    );
  }

  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentMatchesSkeleton />;
  }

  const query = searchParams?.toString() ?? "";
  const returnTo = query ? `${pathname}?${query}` : pathname;
  const bracketHref = (encounter: Encounter) =>
    encounter.stage_id === null
      ? undefined
      : `/tournaments/${slug}/bracket?stage=${encounter.stage_id}&match=${encounter.id}`;
  const cardEyebrow = (encounter: Encounter) => {
    const stage = tournament.stages.find((item) => item.id === encounter.stage_id);
    const instant = toDate(encounter.started_at) ?? toDate(encounter.scheduled_at);
    return [
      stage?.name ?? encounter.stage?.name,
      timeTrailing(encounter),
      instant ? format.dateTime(instant, { hour: "2-digit", minute: "2-digit" }) : null
    ]
      .filter(Boolean)
      .join(" · ");
  };

  const blocks = view === "time" ? timeSections?.days ?? [] : roundBlocks;

  const content = (
    <section
      className={styles.publicDataPage}
      aria-label={t("tournamentDetail.matches.sectionLabel")}
    >
      {presentation.showUpdating ? <UpdatingBadge /> : null}

      {presentation.contentState === "empty" ? (
        <TournamentPageState
          state="empty"
          title={t("tournamentDetail.publicPages.matches.emptyTitle")}
          description={t("tournamentDetail.publicPages.matches.emptyDescription")}
        />
      ) : (
        <div className="min-w-0">
          <SectionToolbar
            label={t("tournamentDetail.matches.toolbarLabel")}
            end={
              hasSchedule ? (
                <ViewSegment<MatchesView>
                  param="view"
                  defaultValue="round"
                  label={t("tournamentDetail.matches.viewLabel")}
                  options={[
                    {
                      value: "round",
                      label: <ListOrdered aria-hidden width={14} height={14} />,
                      ariaLabel: t("tournamentDetail.matches.viewRound")
                    },
                    {
                      value: "time",
                      label: <CalendarClock aria-hidden width={14} height={14} />,
                      ariaLabel: t("tournamentDetail.matches.viewTime")
                    }
                  ]}
                />
              ) : undefined
            }
          >
            {/* One stage is no choice: the chips appear only where they filter. */}
            {stages.length > 1 ? (
              <>
                <FilterChip
                  active={stageFilter === null}
                  count={entityFiltered.length}
                  onClick={() => setParams({ stage: null })}
                >
                  {t("tournamentDetail.matches.allStages")}
                </FilterChip>
                {stages.map((stage) => (
                  <FilterChip
                    key={stageKey(stage.id)}
                    active={stageFilter === stageKey(stage.id)}
                    count={
                      entityFiltered.filter((encounter) => encounter.stage_id === stage.id).length
                    }
                    onClick={() => setParams({ stage: stageKey(stage.id) })}
                  >
                    {stage.name || t("common.stage")}
                  </FilterChip>
                ))}
              </>
            ) : null}
            {teamFilter !== null ? (
              <FilterChip
                active
                aria-label={t("tournamentDetail.matches.clearTeamFilter")}
                onClick={() => setParams({ team: null })}
              >
                {t("tournamentDetail.matches.teamFilter", {
                  name: teamName ?? String(teamFilter)
                })}
                <span aria-hidden>×</span>
              </FilterChip>
            ) : teamOptions.length > 0 ? (
              /* Wireframe §7 ②: one "+ Team" chip, not a filter panel. The
                 picker lists every team that played, and the chosen team
                 becomes the removable chip above. */
              <Select value="" onValueChange={(value) => setParams({ team: value })}>
                <SelectTrigger
                  aria-label={t("tournamentDetail.matches.pickTeam")}
                  className="filter-sort h-8 w-auto gap-1.5 shadow-none focus:ring-0 focus:ring-offset-0"
                >
                  <SelectValue placeholder={t("tournamentDetail.matches.addTeam")} />
                </SelectTrigger>
                <SelectContent>
                  {teamOptions.map((team) => (
                    <SelectItem key={team.id} value={String(team.id)}>
                      {team.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : null}
            {mapFilter !== null ? (
              <FilterChip
                active
                aria-label={t("tournamentDetail.matches.clearMapFilter")}
                onClick={() => setParams({ map: null })}
              >
                {t("tournamentDetail.matches.mapFilter", { name: mapName ?? String(mapFilter) })}
                <span aria-hidden>×</span>
              </FilterChip>
            ) : null}
          </SectionToolbar>

          {rows.length === 0 ? (
            <TournamentPageState
              className="mt-4"
              state="filtered-empty"
              onReset={() => setParams({ stage: null, team: null, map: null })}
            />
          ) : (
            /* A scoreboard reads at a column's width. Stretched across a wide
               viewport the two team names drift apart from the score they
               belong to, so the list stops at roughly the wireframe's frame. */
            <div className="max-w-[64rem]">
              {timeSections && timeSections.live.length > 0 ? (
                <section aria-label={t("tournamentDetail.matches.now")}>
                  <h2 className={HEADING_CLASS}>{t("tournamentDetail.matches.now")}</h2>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {timeSections.live.map((encounter) => (
                      <MatchCard
                        key={encounter.id}
                        encounter={encounter}
                        eyebrow={cardEyebrow(encounter)}
                        href={bracketHref(encounter) ?? `/encounters/${encounter.id}`}
                        streamsCount={
                          (liveTeamStreams.has(encounter.home_team_id) ? 1 : 0) +
                          (liveTeamStreams.has(encounter.away_team_id) ? 1 : 0)
                        }
                      />
                    ))}
                  </div>
                </section>
              ) : null}
              {blocks.map((block) => (
                <section key={block.key} aria-label={block.heading}>
                  <h2 className={HEADING_CLASS}>{block.heading}</h2>
                  <div className="border-t border-[color:var(--aqt-border)]">
                    {block.rows.map((row) => (
                      <MatchRow
                        key={row.encounter.id}
                        encounter={row.encounter}
                        leading={row.leading}
                        trailing={row.trailing}
                        bracketHref={bracketHref(row.encounter)}
                        returnTo={returnTo}
                      />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}
        </div>
      )}
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
};

export default TournamentEncountersPage;
