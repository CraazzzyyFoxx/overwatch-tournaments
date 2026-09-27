"use client";

import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { bracketRoundShape } from "@/lib/bracket/view";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { useQueryParams } from "@/hooks/useQueryParams";
import { tournamentEncountersQueryOptions } from "@/lib/tournament/encounters-query";
import { areStreamsVisible } from "@/lib/tournament/status";
import type { Encounter } from "@/types/encounter.types";

import styles from "../TournamentDetail.module.css";
import { MatchCard } from "../_components/MatchCard";
import { MatchRow } from "../_components/MatchRow";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentMatchesSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { readViewParam } from "../_components/ViewSegment";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { useTournamentStreamsQuery } from "../_hooks/useTournamentStreams";
import { buildLiveTeamStreams } from "../bracket/bracketLiveStreams";
import { getPublicPageQueryPresentation } from "@/lib/public-page-query-presentation";
import { MatchesToolbar } from "./_components/MatchesToolbar";
import {
  buildStageBlocks,
  buildTimeSections,
  collectStages,
  isEliminationStageType,
  MATCHES_VIEWS,
  stageKey,
  toDate,
  type MatchesView
} from "./tournamentMatches.model";

const HEADING_CLASS =
  "aqt-tnum mb-1 mt-5 text-label uppercase tracking-[.06em] text-[color:var(--aqt-fg-faint)]";

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
  const stageCounts = new Map(
    stages.map((stage) => [
      stageKey(stage.id),
      entityFiltered.filter((encounter) => encounter.stage_id === stage.id).length
    ])
  );
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
    const shape = bracketRoundShape(
      type,
      encounters.filter((row) => row.stage_id === encounter.stage_id)
    );
    if (isEliminationStageType(type)) {
      return `${roundLabel(encounter.round, shape)} · ${bo}`;
    }
    return [
      roundLabel(encounter.round, shape),
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
          <MatchesToolbar
            stages={stages}
            stageFilter={stageFilter}
            stageCounts={stageCounts}
            totalCount={entityFiltered.length}
            hasSchedule={hasSchedule}
            teamFilter={teamFilter}
            teamName={teamName}
            teamOptions={teamOptions}
            mapFilter={mapFilter}
            mapName={mapName}
            setParams={setParams}
          />

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
