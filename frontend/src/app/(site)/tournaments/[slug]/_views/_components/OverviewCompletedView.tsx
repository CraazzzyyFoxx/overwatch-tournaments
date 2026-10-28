"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import PlayerName from "@/components/PlayerName";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { ProfileStat } from "@/components/profile/atoms";
import { TeamLogo } from "@/components/TeamName";
import { Eyebrow } from "@/components/ui/eyebrow";
import { PlaceBadge } from "@/components/ui/place-badge";
import { Separator } from "@/components/ui/separator";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import type { BracketRoundShape } from "@/lib/bracket/round-name";
import { useFormatter } from "@/lib/datetime/client";
import { seatAt } from "@/lib/encounter/seats";
import { getEncounterWinner } from "@/lib/encounter/status";
import { getPlayerSlug, splitHandle } from "@/lib/player";
import type { RoleOntology } from "@/lib/roster/ontology";
import type { TournamentInsights } from "@/lib/tournament/insights-query";
import { cn } from "@/lib/utils";
import type { Encounter, EncounterTeam } from "@/types/encounter.types";
import type { Team } from "@/types/team.types";
import type { StageSummary, Standings, Tournament } from "@/types/tournament.types";
import type { CharacterPlaytime } from "@/types/user.types";

import { useTournamentInsights } from "../../_hooks/useTournamentInsights";
import { Podium, type PodiumTeam } from "../../_components/Podium";
import {
  aggregateBans,
  baseRole,
  isTournamentRole,
  rankLabel,
  ROLE_ORDER,
  seriesFor,
  type TeamSeries
} from "../tournamentInsights.model";
import {
  ELIMINATION_TYPES,
  findGrandFinal,
  findLowerFinal,
  rosterBattletags,
  tournamentDaySpan
} from "../tournamentOverview.model";
import {
  useTournamentRoster,
  useViewerUserId,
  type TournamentRoster
} from "../useTournamentRoster";
import { AboutTournamentCard, CardColumns, OverviewSection, SectionLink } from "./OverviewCards";
import { BansCard, TeamSeriesRow, useHeroCatalog } from "./OverviewInsightCards";

type Ontology = RoleOntology | null;

/** The five characters the tournament was actually played on, by share of playtime. */
function TopHeroesCard({
  topHeroes,
  overviewHref
}: Readonly<{ topHeroes: readonly CharacterPlaytime[]; overviewHref: string }>) {
  const t = useTranslations();
  const format = useFormatter();

  return (
    <OverviewSection
      title={t("tournamentDetail.overview.heroes.title")}
      action={
        <SectionLink href={`${overviewHref}/stats?tab=heroes`}>
          {t("tournamentDetail.overview.heroes.all")}
        </SectionLink>
      }
    >
      <ol className="grid gap-1.5">
        {topHeroes.map((entry, index) => {
          const share = Math.min(100, Math.max(0, entry.playtime * 100));
          const widest = Math.min(100, Math.max(0, topHeroes[0].playtime * 100));
          return (
            <li
              className="grid grid-cols-[1rem_1.5rem_minmax(0,1fr)_auto_2.75rem] items-center gap-2"
              key={entry.entity.id}
            >
              <span className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]" aria-hidden>
                {String(index + 1).padStart(2, "0")}
              </span>
              <CatalogEntityImage entity={entry.entity} size={24} decorative />
              <span className="min-w-0 truncate text-caption" title={entry.entity.name}>
                {entry.entity.name}
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
    </OverviewSection>
  );
}

/**
 * The finished tournament's podium: off the grand final (and the lower final
 * for third) of a bracket, else off the standings of a group-only event.
 */
function useCompletedPodium({
  encounters,
  standings,
  teams,
  stage,
  stageId,
  roundShape,
  podiumNeedsStandings
}: Readonly<{
  encounters: readonly Encounter[];
  standings: readonly Standings[];
  teams: readonly Team[];
  stage: StageSummary | null;
  stageId: number | null;
  roundShape: BracketRoundShape;
  podiumNeedsStandings: boolean;
}>) {
  const t = useTranslations();

  const roundLabel = useBracketRoundLabel();

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

  const podiumTeam = (
    entry: EncounterTeam | Team | null | undefined,
    note: string | null
  ): PodiumTeam | null => {
    if (!entry) return null;
    // A seat names its source team by `team_id`; a team read is the team itself.
    const id = "slot" in entry ? (entry.team_id ?? entry.id) : entry.id;
    const image_url = "slot" in entry ? entry.team?.image_url : entry.image_url;
    return { id, name: entry.name, image_url, note };
  };

  let podium: { first: PodiumTeam; second: PodiumTeam; third: PodiumTeam | null } | null = null;

  if (grandFinal) {
    // A drawn final has no champion; slot 1 stands in, as it always led the card.
    const championSlot = getEncounterWinner(grandFinal) ?? 1;
    const champion = seatAt(grandFinal.teams, championSlot);
    const runnerUp = seatAt(grandFinal.teams, championSlot === 1 ? 2 : 1);
    const championScore = champion?.score ?? 0;
    const runnerUpScore = runnerUp?.score ?? 0;
    // The roster comes off the teams read; the encounters read carries no players.
    const roster = rosterBattletags(teamById.get(champion?.team_id ?? -1) ?? champion?.team);
    const first = podiumTeam(champion, roster.length > 0 ? roster : null);
    const second = podiumTeam(
      runnerUp,
      t("tournamentDetail.overview.result.finalScore", {
        score: `${runnerUpScore}–${championScore}`
      })
    );
    let third: PodiumTeam | null = null;
    if (lowerFinal) {
      const lowerWinner = getEncounterWinner(lowerFinal);
      third = podiumTeam(
        seatAt(lowerFinal.teams, lowerWinner === 1 ? 2 : 1),
        t("tournamentDetail.overview.result.exitedIn", {
          round: roundLabel(lowerFinal.round, roundShape)
        })
      );
    }
    if (first && second) podium = { first, second, third };
  } else if (podiumNeedsStandings) {
    // Group-only: third by standings (plan §5).
    // One row per team: across consecutive group stages a team owns several
    // standings, and unranked rows sit at overall_position 0.
    const seenTeams = new Set<number>();
    const ranked = [...standings]
      .sort((left, right) => left.overall_position - right.overall_position)
      .filter((row) => {
        if (row.overall_position <= 0 || seenTeams.has(row.team_id)) return false;
        seenTeams.add(row.team_id);
        return true;
      });
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

  return podium;
}

/**
 * Once it is over: the result, the leaders by role and the numbers, the viewer's own tournament first. The
 * reference — description, format, links — is ONE card in the wide column instead of a tail in the narrow one.
 */
export function OverviewCompletedView({
  tournament,
  slug,
  encounters,
  standings,
  teams,
  topHeroes,
  stage,
  stageId,
  roundShape,
  podiumNeedsStandings,
  miniBracket,
  groupTable,
  aboutCard,
  formatCard,
  linksCard
}: Readonly<{
  tournament: Tournament;
  slug: string;
  encounters: readonly Encounter[];
  standings: readonly Standings[];
  teams: readonly Team[];
  topHeroes: readonly CharacterPlaytime[];
  stage: StageSummary | null;
  stageId: number | null;
  roundShape: BracketRoundShape;
  podiumNeedsStandings: boolean;
  miniBracket: React.ReactNode;
  groupTable: React.ReactNode;
  aboutCard: React.ReactNode;
  formatCard: React.ReactNode;
  linksCard: React.ReactNode;
}>) {
  const t = useTranslations("tournamentDetail");
  const overviewHref = `/tournaments/${slug}`;
  const insights = useTournamentInsights(tournament);
  const podium = useCompletedPodium({
    encounters,
    standings,
    teams,
    stage,
    stageId,
    roundShape,
    podiumNeedsStandings
  });
  const roster = useTournamentRoster(tournament);
  const viewerId = useViewerUserId((id) => roster.byUser.has(id));
  const ontology =
    useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;
  const heroes = useHeroCatalog(tournament.discipline);
  const bans = useMemo(
    () => aggregateBans(insights.heroBans, insights.mapBans),
    [insights.heroBans, insights.mapBans]
  );
  const grandFinal = stageId === null ? null : findGrandFinal(encounters, stageId);

  return (
    <div className="grid min-w-0 gap-4">
      {viewerId ? (
        <MyTournamentCard
          viewerId={viewerId}
          roster={roster}
          encounters={encounters}
          insights={insights}
          ontology={ontology}
          roundShape={roundShape}
          stageId={stageId}
        />
      ) : null}
      <CardColumns
        main={
          <>
            {podium ? (
              <OverviewSection
                title={t("overview.result.title")}
                action={
                  grandFinal ? (
                    <SectionLink href={`/encounters/${grandFinal.id}`}>
                      {t("overview.result.grandFinal")}
                    </SectionLink>
                  ) : null
                }
              >
                <Podium first={podium.first} second={podium.second} third={podium.third} />
              </OverviewSection>
            ) : null}
            <RoleLeadersCard
              roster={roster}
              insights={insights}
              ontology={ontology}
              overviewHref={overviewHref}
            />
            {miniBracket}
            {groupTable}
            <AboutTournamentCard
              aboutCard={aboutCard}
              formatCard={formatCard}
              linksCard={linksCard}
            />
          </>
        }
        side={
          <>
            <NumbersCard
              tournament={tournament}
              encounters={encounters}
              insights={insights}
              heroBans={bans?.totalHeroBans}
              series={bans?.series}
            />
            {bans ? (
              <BansCard
                bans={bans}
                heroes={heroes}
                roster={roster}
                overviewHref={overviewHref}
                limit={8}
              />
            ) : null}
            {insights.draft ? (
              <DraftCard
                insights={insights}
                roster={roster}
                championId={podium?.first.id ?? null}
                overviewHref={overviewHref}
              />
            ) : null}
            {topHeroes.length > 0 ? (
              <TopHeroesCard topHeroes={topHeroes} overviewHref={overviewHref} />
            ) : null}
          </>
        }
      />
    </div>
  );
}

function MyTournamentCard({
  viewerId,
  roster,
  encounters,
  insights,
  ontology,
  roundShape,
  stageId
}: Readonly<{
  viewerId: number;
  roster: TournamentRoster;
  encounters: readonly Encounter[];
  insights: TournamentInsights;
  ontology: Ontology;
  roundShape: BracketRoundShape;
  stageId: number | null;
}>) {
  const t = useTranslations("tournamentDetail");
  const format = useFormatter();
  const roundLabel = useBracketRoundLabel();
  const entry = roster.byUser.get(viewerId);
  if (!entry) return null;
  const { player, team } = entry;
  const stats = insights.players[viewerId] ?? {};
  const role = baseRole(player.role?.role);
  // The viewer's place among players of their own role, by the same MVP measure.
  const sameRole = [...roster.byUser.values()]
    .filter(({ player: other }) => baseRole(other.role?.role) === role)
    .map(({ player: other }) => insights.players[other.user_id]?.performance?.value)
    .filter((value): value is number => value != null)
    .sort((a, b) => a - b);
  const roleRank = stats.performance ? sameRole.indexOf(stats.performance.value) + 1 : null;

  const series = encounters
    .map((encounter) => ({ encounter, seat: seriesFor(encounter, team.id) }))
    .filter((row): row is { encounter: Encounter; seat: TeamSeries } => row.seat !== null)
    .sort(
      (a, b) =>
        (a.encounter.played_at ?? "").localeCompare(b.encounter.played_at ?? "") ||
        a.encounter.id - b.encounter.id
    );
  const won = series.filter((row) => row.seat.result === "w").length;
  const lost = series.filter((row) => row.seat.result === "l").length;
  const draws = series.length - won - lost;
  const mapsWon = series.reduce((sum, row) => sum + row.seat.mine.score, 0);
  const mapsLost = series.reduce((sum, row) => sum + row.seat.theirs.score, 0);
  const number = (value: number, digits: number) =>
    format.number(value, { maximumFractionDigits: digits, minimumFractionDigits: digits });

  return (
    <OverviewSection
      title={t("overview.my.title")}
      action={
        <SectionLink href={`/users/${getPlayerSlug(player.name)}`}>
          {t("overview.my.profile")}
        </SectionLink>
      }
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-x-10">
        <div className="grid content-start gap-6">
          <div className="flex items-center justify-between gap-4">
            <div className="flex min-w-0 items-center gap-3">
              <TeamLogo team={team} size="lg" />
              <div className="min-w-0">
                <p className="truncate font-onest text-heading font-semibold" title={team.name}>
                  {team.name}
                </p>
                <p className="mt-0.5 flex items-center gap-1.5 text-caption text-[color:var(--aqt-fg-muted)]">
                  <PlayerRoleIcon role={player.role} ontology={ontology} size={14} decorative />
                  {splitHandle(player.name).name}
                </p>
              </div>
            </div>
            {team.placement ? (
              <div className="flex shrink-0 flex-col items-center gap-1">
                <PlaceBadge place={team.placement} size="md" />
                <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
                  {t("common.ofTotal", { total: roster.teams.length })}
                </span>
              </div>
            ) : null}
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4 lg:grid-cols-2">
            <ProfileStat
              label={t("stats.metrics.performance.label")}
              title={t("stats.performanceHint")}
              value={stats.performance ? number(stats.performance.value, 2) : "—"}
              sub={
                stats.performance
                  ? t("common.rankOf", {
                      rank: stats.performance.rank,
                      total: insights.playersTotal
                    })
                  : t("common.noLogs")
              }
            />
            <ProfileStat
              label={t("overview.my.roleRank")}
              value={roleRank ? `#${roleRank}` : "—"}
              sub={
                roleRank && isTournamentRole(role)
                  ? t("overview.my.roleRankSub", {
                      count: sameRole.length,
                      role: t(`roleOf.${role}`)
                    })
                  : undefined
              }
            />
            <ProfileStat
              label={t("stats.metrics.kda.label")}
              value={stats.kda ? number(stats.kda.value, 2) : "—"}
              sub={stats.kda ? t("common.rankInTournament", { rank: stats.kda.rank }) : undefined}
            />
            <ProfileStat
              label={t("overview.my.series")}
              value={`${won}–${lost}`}
              sub={t("overview.my.seriesSub", { draws, won: mapsWon, lost: mapsLost })}
            />
          </div>
        </div>
        <div className="lg:border-l lg:border-[color:var(--aqt-border)] lg:pl-10">
          <Eyebrow as="h3" className="mb-1 block">
            {t("overview.my.matches")}
          </Eyebrow>
          <ol className="-mx-2 divide-y divide-[color:var(--aqt-border)]">
            {series.map(({ encounter, seat }) => (
              <li key={encounter.id}>
                <TeamSeriesRow
                  encounter={encounter}
                  seat={seat}
                  round={
                    encounter.stage_id === stageId
                      ? roundLabel(encounter.round, roundShape)
                      : t("common.round", { round: encounter.round })
                  }
                />
              </li>
            ))}
          </ol>
        </div>
      </div>
    </OverviewSection>
  );
}

function RoleLeadersCard({
  roster,
  insights,
  ontology,
  overviewHref
}: Readonly<{
  roster: TournamentRoster;
  insights: TournamentInsights;
  ontology: Ontology;
  overviewHref: string;
}>) {
  const t = useTranslations("tournamentDetail");
  const format = useFormatter();
  const columns = ROLE_ORDER.map((role) => {
    const rows = [...roster.byUser.values()]
      .filter(
        ({ player }) =>
          baseRole(player.role?.role) === role && insights.players[player.user_id]?.performance
      )
      .sort(
        (a, b) =>
          (insights.players[a.player.user_id]?.performance?.value ?? 0) -
          (insights.players[b.player.user_id]?.performance?.value ?? 0)
      )
      .slice(0, 3);
    return { role, rows };
  }).filter((column) => column.rows.length > 0);
  if (columns.length === 0) return null;

  return (
    <OverviewSection
      title={t("overview.leaders.title")}
      action={
        <SectionLink href={`${overviewHref}/stats?tab=players`}>
          {t("common.allPlayers")}
        </SectionLink>
      }
    >
      <div className="grid gap-5 sm:grid-cols-3">
        {columns.map(({ role, rows }) => (
          <div key={role} className="min-w-0">
            <p className="mb-2 flex items-center gap-2 text-caption font-semibold">
              <PlayerRoleIcon role={rows[0].player.role} ontology={ontology} size={16} decorative />
              {t(`roles.${role}`)}
            </p>
            <ol className="grid gap-2">
              {rows.map(({ player, team }, index) => (
                <li
                  key={player.id}
                  className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] items-center gap-2"
                >
                  <span
                    aria-hidden
                    className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]"
                  >
                    {rankLabel(index)}
                  </span>
                  <span className="min-w-0">
                    <PlayerName player={player} className="text-caption" />
                    <span className="block truncate text-label text-[color:var(--aqt-fg-dim)]">
                      {team.name}
                    </span>
                  </span>
                  <span
                    className={cn(
                      "aqt-tnum text-caption font-semibold",
                      index === 0 && "text-[color:var(--aqt-teal)]"
                    )}
                  >
                    {format.number(insights.players[player.user_id]?.performance?.value ?? 0, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2
                    })}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
      <p className="mt-4 text-label text-[color:var(--aqt-fg-dim)]">{t("stats.performanceHint")}</p>
    </OverviewSection>
  );
}

function NumbersCard({
  tournament,
  encounters,
  insights,
  heroBans,
  series
}: Readonly<{
  tournament: Tournament;
  encounters: readonly Encounter[];
  insights: TournamentInsights;
  heroBans: number | undefined;
  series: number | undefined;
}>) {
  const t = useTranslations("tournamentDetail");
  const format = useFormatter();
  const days = tournamentDaySpan(tournament.start_date, tournament.end_date);
  const autopicks = insights.draft?.picks.filter((pick) => pick.autopick).length ?? 0;
  return (
    <OverviewSection title={t("overview.numbers.title")}>
      <div className="grid grid-cols-2 gap-x-6 gap-y-5">
        <ProfileStat
          label={t("overview.numbers.matches")}
          value={format.number(encounters.length)}
          size="md"
        />
        {days !== null ? (
          <ProfileStat label={t("overview.numbers.days")} value={days} size="md" />
        ) : null}
        {heroBans ? (
          <ProfileStat
            label={t("overview.numbers.heroBans")}
            value={format.number(heroBans)}
            sub={t("overview.numbers.inSeries", { count: series ?? 0 })}
            size="md"
          />
        ) : null}
        {insights.draft ? (
          <ProfileStat
            label={t("overview.numbers.draftPicks")}
            value={format.number(insights.draft.picks.length)}
            sub={t("overview.numbers.autopicks", { count: autopicks })}
            size="md"
          />
        ) : null}
      </div>
    </OverviewSection>
  );
}

function DraftCard({
  insights,
  roster,
  championId,
  overviewHref
}: Readonly<{
  insights: TournamentInsights;
  roster: TournamentRoster;
  championId: number | null;
  overviewHref: string;
}>) {
  const t = useTranslations("tournamentDetail");
  const format = useFormatter();
  const draft = insights.draft;
  if (!draft) return null;
  const bySr = [...roster.teams].sort((a, b) => b.avg_sr - a.avg_sr);
  const championSrRank =
    championId === null ? 0 : bySr.findIndex((team) => team.id === championId) + 1;
  // A late pick is one of the last two rounds; the best of them by the MVP measure.
  const lateFrom = Math.max(2, draft.rounds - 1);
  const steal = draft.picks
    .filter(
      (pick) =>
        pick.round >= lateFrom && pick.userId != null && insights.players[pick.userId]?.performance
    )
    .sort(
      (a, b) =>
        (insights.players[a.userId as number]?.performance?.value ?? 99) -
        (insights.players[b.userId as number]?.performance?.value ?? 99)
    )[0];
  const stealTeam = steal?.teamId != null ? roster.byTeam.get(steal.teamId) : undefined;
  const stealStat = steal?.userId != null ? insights.players[steal.userId]?.performance : undefined;

  return (
    <OverviewSection
      title={t("overview.draftCard.title")}
      action={
        <SectionLink href={`${overviewHref}/participants`}>
          {t("overview.draftCard.allPicks")}
        </SectionLink>
      }
    >
      <div className="grid gap-4">
        {championSrRank > 0 ? (
          <ProfileStat
            label={t("overview.draftCard.championStrength")}
            value={t("overview.draftCard.championRank", { rank: championSrRank })}
            sub={t("overview.draftCard.championRankSub", { total: bySr.length })}
            size="md"
          />
        ) : null}
        {steal && stealStat ? (
          <>
            <Separator />
            <div>
              <Eyebrow className="block">{t("overview.draftCard.latePick")}</Eyebrow>
              <div className="mt-2 flex items-center justify-between gap-3">
                <span className="min-w-0">
                  <PlayerName player={{ name: steal.name }} className="text-caption" />
                  <span className="block truncate text-label text-[color:var(--aqt-fg-dim)]">
                    {t("overview.draftCard.pickLine", {
                      round: steal.round,
                      overall: steal.overall
                    })}
                    {stealTeam ? `, ${stealTeam.name}` : ""}
                  </span>
                </span>
                <span className="shrink-0 text-right">
                  <span className="aqt-tnum block text-caption font-semibold text-[color:var(--aqt-teal)]">
                    {format.number(stealStat.value, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2
                    })}
                  </span>
                  <span className="aqt-tnum block text-label text-[color:var(--aqt-fg-dim)]">
                    {t("common.rankInTournament", { rank: stealStat.rank })}
                  </span>
                </span>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </OverviewSection>
  );
}
