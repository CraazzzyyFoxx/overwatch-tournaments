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
import { groupDisplayName } from "@/lib/tournament/group";
import { useFfaStageLobbies } from "../_hooks/useFfaStageLobbies";
import { MatchesFfaLobbies } from "./_components/MatchesFfaLobbies";
import { MatchesToolbar } from "./_components/MatchesToolbar";
import {
  buildStageBlocks,
  buildTimeSections,
  collectStages,
  isEliminationStageType,
  MATCHES_VIEWS,
  stageKey,
  toDate,
  type MatchBlock,
  type MatchesView
} from "./tournamentMatches.model";

const HEADING_CLASS =
  "aqt-tnum mb-1 mt-5 text-label uppercase tracking-[.06em] text-[color:var(--aqt-fg-faint)]";

/** The stage over its rounds. Every round heading used to carry the stage name
 *  glued in front of it ("DOUBLE ELIMINATION · UB Final"); it is said once here
 *  instead, so the round is what a round heading says. */
const STAGE_HEADING_CLASS = "mb-1 mt-6 text-ui font-semibold text-[color:var(--aqt-fg)]";

/** The section fills its container, so a wide viewport would otherwise stretch
 *  the two name tracks and leave the chevron alone at the far edge. Here the
 *  names sit in fixed tracks around the score and the spare width goes to the
 *  outer tracks, keeping time · teams · score · format · chevron one block. */
const WIDE_ROW_CLASS = "lg:grid-cols-[minmax(0,1fr)_14rem_5.5rem_14rem_minmax(0,1fr)]";

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

  // The encounter list answers duels only; an FFA stage's matches are its lobbies.
  const ffa = useFfaStageLobbies(tournament);

  const encounters = encountersQuery.data?.results ?? [];
  const presentation = getPublicPageQueryPresentation({
    // Held until the lobbies land too, or an FFA-only tournament flashes the
    // "no matches" state first.
    data: ffa.isPending ? undefined : encountersQuery.data,
    itemCount: encounters.length + ffa.lobbies.length,
    isPending: encountersQuery.isPending || ffa.isPending,
    isError: encountersQuery.isError,
    isFetching: encountersQuery.isFetching || ffa.isFetching
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
  // A lobby has no maps and no stage chip (the chips are the duel stages), so
  // either filter leaves only duels; a team filter keeps the lobbies it sits in.
  const entityLobbies =
    mapFilter !== null
      ? []
      : ffa.lobbies.filter(
          (lobby) => teamFilter === null || lobby.rows.some((row) => row.team_id === teamFilter)
        );
  const lobbies = stageFilter === null ? entityLobbies : [];

  const teamName =
    teamFilter === null
      ? null
      : (encounters
          .map((encounter) =>
            encounter.home_team_id === teamFilter
              ? encounter.home_team?.name
              : encounter.away_team_id === teamFilter
                ? encounter.away_team?.name
                : null
          )
          .find(Boolean) ??
        ffa.lobbies.flatMap((lobby) => lobby.rows).find((row) => row.team_id === teamFilter)
          ?.team_name ??
        null);
  /** Every team with a match or a lobby seat, once, by name — the picker's options. */
  const teamOptions = (() => {
    const byId: Record<number, string> = {};
    for (const encounter of encounters) {
      if (encounter.home_team) byId[encounter.home_team_id] = encounter.home_team.name;
      if (encounter.away_team) byId[encounter.away_team_id] = encounter.away_team.name;
    }
    for (const lobby of ffa.lobbies) {
      for (const row of lobby.rows) byId[row.team_id] = row.team_name;
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
      name ? groupDisplayName(name, groupWord) : null,
      bo
    ]
      .filter(Boolean)
      .join(" · ");
  };

  /**
   * The round view, one entry per stage: the stage names the block of rounds
   * below it, so no round heading has to repeat it.
   */
  const stageGroups =
    view === "round" && tournament
      ? collectStages(rows, tournament).map((stage) => ({
          key: stageKey(stage.id),
          name: stage.name,
          blocks: buildStageBlocks(
            stage,
            rows.filter((encounter) => encounter.stage_id === stage.id),
            roundLabel,
            countLabel
          )
        }))
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

  /** Both views as one shape: a named stage with its rounds, or one unnamed day list. */
  const groups: { key: string; name: string; blocks: MatchBlock[] }[] =
    view === "time"
      ? [{ key: "time", name: "", blocks: timeSections?.days ?? [] }]
      : stageGroups;

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
            totalCount={entityFiltered.length + entityLobbies.length}
            hasSchedule={hasSchedule}
            teamFilter={teamFilter}
            teamName={teamName}
            teamOptions={teamOptions}
            mapFilter={mapFilter}
            mapName={mapName}
            setParams={setParams}
          />

          {rows.length === 0 && lobbies.length === 0 ? (
            <TournamentPageState
              className="mt-4"
              state="filtered-empty"
              onReset={() => setParams({ stage: null, team: null, map: null })}
            />
          ) : (
            /* Full container width: the scoreboard no longer needs the list
               narrowed to keep the two team names near their score — the row
               itself bounds them (`MatchRow`), so the slack sits outside the
               cluster instead of pushing the chevron off to a far edge. */
            <div className="min-w-0">
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
              {groups.map((group) => (
                <section key={group.key} aria-label={group.name || undefined}>
                  {group.name ? (
                    <h2 className={STAGE_HEADING_CLASS}>{group.name}</h2>
                  ) : null}
                  {group.blocks.map((block) => (
                    <section key={block.key} aria-label={block.heading}>
                      {group.name ? (
                        <h3 className={HEADING_CLASS}>{block.heading}</h3>
                      ) : (
                        <h2 className={HEADING_CLASS}>{block.heading}</h2>
                      )}
                      <div className="border-t border-[color:var(--aqt-border)]">
                        {block.rows.map((row) => (
                          <MatchRow
                            key={row.encounter.id}
                            encounter={row.encounter}
                            leading={row.leading}
                            trailing={row.trailing}
                            bracketHref={bracketHref(row.encounter)}
                            returnTo={returnTo}
                            className={WIDE_ROW_CLASS}
                          />
                        ))}
                      </div>
                    </section>
                  ))}
                </section>
              ))}
              <MatchesFfaLobbies
                tournament={tournament}
                lobbies={lobbies}
                headingClassName={HEADING_CLASS}
              />
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
