"use client";

import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { TournamentTeamCardFrame } from "@/components/TournamentTeamCard";
import { Badge } from "@/components/ui/badge";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { FilterChip } from "@/components/ui/filter-chip";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { useQueryParams } from "@/hooks/useQueryParams";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { bracketRoundShape } from "@/lib/bracket/view";
import { useFormatter } from "@/lib/datetime/client";
import { getPublicPageQueryPresentation } from "@/lib/public-page-query-presentation";
import { tournamentEncountersQueryOptions } from "@/lib/tournament/encounters-query";
import { groupDisplayName, groupHue } from "@/lib/tournament/group";
import { areStreamsVisible } from "@/lib/tournament/status";
import { cn } from "@/lib/utils";
import type { Encounter } from "@/types/encounter.types";
import type { Tournament } from "@/types/tournament.types";

import { MatchCard } from "../_components/MatchCard";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentMatchesSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { readViewParam } from "../_components/ViewSegment";
import { useFfaStageLobbies } from "../_hooks/useFfaStageLobbies";
import { useTournamentStreamsQuery } from "../_hooks/useTournamentStreams";
import { MatchesFfaLobbies } from "./_components/MatchesFfaLobbies";
import { MatchesToolbar } from "./_components/MatchesToolbar";
import {
  buildStageBlocks,
  buildTimeSections,
  collectStages,
  isEliminationStageType,
  MATCHES_VIEWS,
  stageKey,
  type MatchBlock,
  type MatchesView
} from "./tournamentMatches.model";
import { buildLiveTeamStreams } from "../bracket/bracketLiveStreams";
import { CardColumns } from "./_components/OverviewCards";
import { balanceColumns } from "./tournamentInsights.model";
import { useTournamentRoster, useViewerUserId } from "./useTournamentRoster";
import { MatchRow } from "../_components/MatchRow";

type MatchListRow = MatchBlock["rows"][number];

const HEADING_CLASS = `${eyebrowClass()} aqt-tnum mb-1 mt-5`;
const STAGE_HEADING_CLASS = "mt-6 text-ui font-semibold text-[color:var(--aqt-fg)]";

/** A card's height in rows: its header is about one more, the gap under it a third. */
const blockWeight = (block: MatchBlock) => block.rows.length + 1.3;

/**
 * The tournament's matches, laid out so no column runs past the other: a group stage's round is one card with its
 * groups side by side, any other stage's rounds split into two even columns in reading order (a bracket's final
 * first, then down the upper bracket, then down the lower). Under 640px a match is one line, its maps a tap away.
 */
export default function TournamentEncountersPage({
  tournament: overview,
  slug
}: Readonly<{ tournament: Tournament; slug: string }>) {
  const t = useTranslations();
  const tp = useTranslations("tournamentDetail");
  const format = useFormatter();
  const pathname = usePathname();
  const roundLabel = useBracketRoundLabel();
  const { searchParams, setParams } = useQueryParams();
  const minute = useMinuteClock();

  // The server's overview until the client's own read (same cache entry) has it.
  const tournament = useTournamentQuery(slug).data ?? overview;
  const encountersQuery = useQuery(tournamentEncountersQueryOptions(tournament));
  const streamsQuery = useTournamentStreamsQuery(
    areStreamsVisible(tournament.status) ? tournament.id : undefined
  );
  const ffa = useFfaStageLobbies(tournament);
  const roster = useTournamentRoster(tournament);
  const viewerId = useViewerUserId((id) => roster.byUser.has(id));
  const myTeamId = viewerId === null ? null : (roster.byUser.get(viewerId)?.team.id ?? null);

  const encounters = encountersQuery.data?.results ?? [];
  const presentation = getPublicPageQueryPresentation({
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

  const hasSchedule = encounters.some((encounter) => encounter.scheduled_at != null);
  const requestedView = readViewParam<MatchesView>(searchParams, "view", MATCHES_VIEWS, "round");
  const view: MatchesView = hasSchedule ? requestedView : "round";

  const entityFiltered = encounters.filter(
    (encounter) =>
      (teamFilter === null || encounter.teams.some((seat) => seat.team_id === teamFilter)) &&
      (mapFilter === null || (encounter.matches ?? []).some((match) => match.map_id === mapFilter))
  );
  const stages = collectStages(entityFiltered, tournament);
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
  const entityLobbies =
    mapFilter !== null
      ? []
      : ffa.lobbies.filter(
          (lobby) => teamFilter === null || lobby.rows.some((row) => row.team_id === teamFilter)
        );
  const lobbies = stageFilter === null ? entityLobbies : [];

  const teamNames = new Map<number, string>();
  for (const encounter of encounters) {
    for (const seat of encounter.teams)
      if (seat.team_id != null) teamNames.set(seat.team_id, seat.name);
  }
  for (const lobby of ffa.lobbies)
    for (const row of lobby.rows) teamNames.set(row.team_id, row.team_name);
  const teamOptions = [...teamNames]
    .map(([id, name]) => ({ id, name }))
    .sort((left, right) => left.name.localeCompare(right.name));
  const mapName =
    mapFilter === null
      ? null
      : (encounters
          .flatMap((encounter) => encounter.matches ?? [])
          .find((match) => match.map_id === mapFilter)?.map?.name ?? null);

  const countLabel = (count: number) => t("tournamentDetail.matches.matchCount", { count });
  const groupWord = t("common.group");
  const liveTeamStreams = buildLiveTeamStreams(streamsQuery.data);

  const timeTrailing = (encounter: Encounter) => {
    const stage = tournament.stages.find((item) => item.id === encounter.stage_id);
    const type = stage?.stage_type ?? encounter.stage?.stage_type;
    const shape = bracketRoundShape(
      type,
      encounters.filter((row) => row.stage_id === encounter.stage_id)
    );
    const name = encounter.stage_item?.name;
    return [
      roundLabel(encounter.round, shape),
      !isEliminationStageType(type) && name ? groupDisplayName(name, groupWord) : null,
      `Bo${encounter.best_of}`
    ]
      .filter(Boolean)
      .join(" · ");
  };

  if (presentation.initialState === "error") {
    return (
      <TournamentPageState state="initial-error" onRetry={() => void encountersQuery.refetch()} />
    );
  }
  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentMatchesSkeleton />;
  }

  const stageGroups =
    view === "round"
      ? collectStages(rows, tournament).map((stage) => {
          const stageRows = rows.filter((encounter) => encounter.stage_id === stage.id);
          const blocks = buildStageBlocks(stage, stageRows, roundLabel, countLabel);
          const elimination = isEliminationStageType(stage.type);
          // A bracket reads final first, then down the upper bracket, then down the lower: `buildStageBlocks`
          // interleaves the two.
          const { finalRounds } = bracketRoundShape(stage.type, stageRows);
          const side = (round: number) => (finalRounds.includes(round) ? 0 : round > 0 ? 1 : 2);
          return {
            key: stageKey(stage.id),
            name: stage.name,
            grouped: !elimination,
            blocks: elimination
              ? [...blocks].sort((a, b) => {
                  const ra = a.rows[0]?.encounter.round ?? 0;
                  const rb = b.rows[0]?.encounter.round ?? 0;
                  return side(ra) - side(rb) || (side(ra) === 2 ? ra - rb : rb - ra);
                })
              : blocks
          };
        })
      : [];
  const timeSections =
    view === "time" && minute !== null
      ? buildTimeSections(rows, new Date(minute), {
          day: (date) =>
            format.dateTime(date, { weekday: "short", day: "numeric", month: "short" }),
          time: (date) => format.dateTime(date, { hour: "2-digit", minute: "2-digit" }),
          laterToday: t("tournamentDetail.matches.laterToday"),
          unscheduled: t("tournamentDetail.matches.unscheduled"),
          phase: () => null,
          trailing: timeTrailing,
          count: countLabel
        })
      : null;
  const groups =
    view === "time"
      ? [{ key: "time", name: "", grouped: false, blocks: timeSections?.days ?? [] }]
      : stageGroups;

  const query = searchParams?.toString() ?? "";
  const returnTo = query ? `${pathname}?${query}` : pathname;
  const bracketHref = (encounter: Encounter) =>
    encounter.stage_id === null
      ? undefined
      : `/tournaments/${slug}/bracket?stage=${encounter.stage_id}&match=${encounter.id}`;
  const match = (row: MatchListRow, withGroup: boolean) => (
    <MatchRow
      key={row.encounter.id}
      encounter={row.encounter}
      leading={
        withGroup && row.group ? (
          <Badge hue={groupHue(row.group)} voice="label">
            {groupDisplayName(row.group, groupWord)}
          </Badge>
        ) : (
          row.leading
        )
      }
      trailing={row.trailing}
      bracketHref={bracketHref(row.encounter)}
      returnTo={returnTo}
    />
  );
  const card = (block: MatchBlock) => (
    <TournamentTeamCardFrame key={block.key} name={block.heading} metricValue={block.meta}>
      {block.rows.map((row) => match(row, true))}
    </TournamentTeamCardFrame>
  );

  const content = (
    <section
      className="grid w-full min-w-0 max-w-full gap-4 *:min-w-0"
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
            teamName={teamFilter === null ? null : (teamNames.get(teamFilter) ?? null)}
            teamOptions={teamOptions}
            mapFilter={mapFilter}
            mapName={mapName}
            setParams={setParams}
          >
            {myTeamId !== null && teamFilter !== myTeamId ? (
              <FilterChip onClick={() => setParams({ team: String(myTeamId) })}>
                {tp("matches.myTeam")}
              </FilterChip>
            ) : null}
          </MatchesToolbar>

          {rows.length === 0 && lobbies.length === 0 ? (
            <TournamentPageState
              className="mt-4"
              state="filtered-empty"
              onReset={() => setParams({ stage: null, team: null, map: null })}
            />
          ) : (
            <div className="min-w-0">
              {timeSections && timeSections.live.length > 0 ? (
                <section aria-label={t("tournamentDetail.matches.now")}>
                  <h2 className={HEADING_CLASS}>{t("tournamentDetail.matches.now")}</h2>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {timeSections.live.map((encounter) => (
                      <MatchCard
                        key={encounter.id}
                        encounter={encounter}
                        eyebrow={timeTrailing(encounter)}
                        href={bracketHref(encounter) ?? `/encounters/${encounter.id}`}
                        streamsCount={
                          encounter.teams.filter(
                            (seat) => seat.team_id != null && liveTeamStreams.has(seat.team_id)
                          ).length
                        }
                      />
                    ))}
                  </div>
                </section>
              ) : null}
              {groups.map((group) => {
                const { left, right, tail } = balanceColumns(group.blocks, blockWeight);
                return (
                  <section key={group.key} aria-label={group.name || undefined}>
                    {group.name ? <h2 className={STAGE_HEADING_CLASS}>{group.name}</h2> : null}
                    <div className="mt-3 grid gap-3">
                      {group.grouped ? (
                        group.blocks.map((block) => (
                          <GroupRoundCard
                            key={block.key}
                            block={block}
                            groupWord={groupWord}
                            match={match}
                          />
                        ))
                      ) : right.length === 0 || left.length === 0 ? (
                        group.blocks.map(card)
                      ) : (
                        <>
                          <CardColumns even main={left.map(card)} side={right.map(card)} />
                          {tail ? card(tail) : null}
                        </>
                      )}
                    </div>
                  </section>
                );
              })}
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
}

/**
 * A group stage's round as one card: its groups side by side under their own labels, so a row needs no group chip and
 * both columns end on the card's edge. A stage without groups splits the round's matches in halves instead.
 */
function GroupRoundCard({
  block,
  groupWord,
  match
}: Readonly<{
  block: MatchBlock;
  groupWord: string;
  match: (row: MatchListRow, withGroup: boolean) => React.ReactNode;
}>) {
  const byGroup = new Map<string, MatchListRow[]>();
  for (const row of block.rows) {
    byGroup.set(row.group ?? "", [...(byGroup.get(row.group ?? "") ?? []), row]);
  }
  // Groups side by side; one group's matches in halves; a lone match (a team filter) keeps the full row.
  const half = Math.ceil(block.rows.length / 2);
  const columns: [string, MatchListRow[]][] =
    byGroup.size > 1
      ? [...byGroup].sort(([a], [b]) => a.localeCompare(b))
      : block.rows.length > 1
        ? [
            ["", block.rows.slice(0, half)],
            ["", block.rows.slice(half)]
          ]
        : [["", block.rows]];
  return (
    <TournamentTeamCardFrame name={block.heading} metricValue={block.meta}>
      <div
        className={cn(
          "grid",
          columns.length > 1 && "lg:grid-cols-2 lg:divide-x lg:divide-[color:var(--aqt-border)]"
        )}
      >
        {columns.map(([group, rows], index) => (
          <div key={group || index} className="min-w-0">
            {group ? (
              <div className="px-3.5 pt-3 pb-1.5">
                <Badge hue={groupHue(group)} voice="label">
                  {groupDisplayName(group, groupWord)}
                </Badge>
              </div>
            ) : null}
            {rows.map((row) => match(row, false))}
          </div>
        ))}
      </div>
    </TournamentTeamCardFrame>
  );
}
