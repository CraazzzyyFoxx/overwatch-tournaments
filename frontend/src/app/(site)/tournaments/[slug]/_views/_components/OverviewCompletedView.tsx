"use client";

import { useTranslations } from "next-intl";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import type { BracketRoundShape } from "@/lib/bracket/round-name";
import { useFormatter } from "@/lib/datetime/client";
import type { Encounter } from "@/types/encounter.types";
import type { HeroPlaytime } from "@/types/hero.types";
import type { Team } from "@/types/team.types";
import type { StageSummary, Standings, Tournament } from "@/types/tournament.types";

import { Podium, type PodiumTeam } from "../../_components/Podium";
import { tournamentPlayersCount } from "../../_components/TournamentClientLayout";
import {
  ELIMINATION_TYPES,
  findGrandFinal,
  findLowerFinal,
  rosterBattletags,
  tournamentDaySpan,
  winnerSide
} from "../tournamentOverview.model";
import { CardLink, OverviewCard } from "./OverviewCards";
import { StatTile } from "./RegistrationSummary";

/** The five heroes the tournament was actually played on, by share of playtime. */
function TopHeroesCard({
  topHeroes,
  overviewHref
}: Readonly<{ topHeroes: readonly HeroPlaytime[]; overviewHref: string }>) {
  const t = useTranslations();
  const format = useFormatter();

  return (
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
              <span className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]" aria-hidden>
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
  );
}

/**
 * C: once it is over (§3C). A finished tournament opens on its result, not on
 * the bracket corner the final happens to sit in.
 */
export function OverviewCompletedView({
  tournament,
  encounters,
  standings,
  teams,
  topHeroes,
  stage,
  stageId,
  roundShape,
  podiumNeedsStandings,
  overviewHref,
  nowBlock,
  miniBracket,
  groupTable,
  formatCard,
  linksCard
}: Readonly<{
  tournament: Tournament;
  encounters: readonly Encounter[];
  standings: readonly Standings[];
  teams: readonly Team[];
  topHeroes: readonly HeroPlaytime[];
  stage: StageSummary | null;
  stageId: number | null;
  roundShape: BracketRoundShape;
  podiumNeedsStandings: boolean;
  overviewHref: string;
  nowBlock: React.ReactNode;
  miniBracket: React.ReactNode;
  groupTable: React.ReactNode;
  formatCard: React.ReactNode;
  linksCard: React.ReactNode;
}>) {
  const t = useTranslations();
  const roundLabel = useBracketRoundLabel();

  const teamsCount = tournament.teams_count ?? 0;
  const playersCount = tournamentPlayersCount(tournament);

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

  const days = tournamentDaySpan(tournament.start_date, tournament.end_date);

  return (
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
          <TopHeroesCard topHeroes={topHeroes} overviewHref={overviewHref} />
        ) : null}
        <OverviewCard title={t("tournamentDetail.overview.numbers.title")}>
          <div className="grid gap-2 sm:grid-cols-2">
            <StatTile
              label={t(tournament.team_formation === "registration" ? "registrationTeams.list.inTournament" : "tournamentDetail.overview.numbers.teams")}
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
  );
}
