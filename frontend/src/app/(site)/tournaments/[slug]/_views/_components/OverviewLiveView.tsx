"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { ResTag } from "@/components/match/cells";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { ProfileStat } from "@/components/profile/atoms";
import TeamName, { TeamLogo } from "@/components/TeamName";
import { Badge } from "@/components/ui/badge";
import { Eyebrow, eyebrowClass } from "@/components/ui/eyebrow";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useFormatter } from "@/lib/datetime/client";
import { isEncounterCompleted, isEncounterLive } from "@/lib/encounter/status";
import { splitHandle } from "@/lib/player";
import type { RoleOntology } from "@/lib/roster/ontology";
import { groupDisplayName } from "@/lib/tournament/group";
import { cn } from "@/lib/utils";
import type { Encounter } from "@/types/encounter.types";
import type { StageSummary, Standings, Tournament } from "@/types/tournament.types";

import { useTournamentInsights } from "../../_hooks/useTournamentInsights";
import { MatchCard } from "../../_components/MatchCard";
import { MatchRow } from "../../_components/MatchRow";
import { aggregateBans, seriesFor, type TeamSeries } from "../tournamentInsights.model";
import {
  buildGroupRows,
  ELIMINATION_TYPES,
  GROUP_TYPES,
  type GroupRow
} from "../tournamentOverview.model";
import type { OverviewMatchPresenter } from "../useOverviewMatchPresenter";
import {
  useTournamentRoster,
  useViewerUserId,
  type TournamentRoster
} from "../useTournamentRoster";
import { AboutTournamentCard, CardColumns, OverviewSection, SectionLink } from "./OverviewCards";
import { BansCard, TeamSeriesRow, useHeroCatalog } from "./OverviewInsightCards";

/**
 * The group tables side by side: place, the last three results, map difference and points. The places that go
 * through are teal down to the cut line, so the race for the last spot reads at a glance.
 */
function GroupTablesCard({
  stage,
  rows,
  overviewHref
}: Readonly<{ stage: StageSummary; rows: readonly GroupRow[]; overviewHref: string }>) {
  const t = useTranslations("tournamentDetail");
  const tRoot = useTranslations();
  const byGroup = new Map<string, GroupRow[]>();
  for (const row of rows) byGroup.set(row.groupKey, [...(byGroup.get(row.groupKey) ?? []), row]);
  const groups = [...byGroup.values()];
  // One decimal everywhere as soon as any row carries a half point: "4" beside "3.5" has no shared decimal to scan.
  const fraction = rows.some((row) => !Number.isInteger(row.points));
  const advance = rows[0]?.advance ?? null;
  const head = "h-auto px-0 py-2 font-medium";
  const cell = "px-0 py-2";

  return (
    <OverviewSection
      title={t("overview.groupTable.title", { stage: stage.name })}
      action={
        <SectionLink href={`${overviewHref}/bracket?stage=${stage.id}&view=standings`}>
          {t("overview.groupTable.open")}
        </SectionLink>
      }
    >
      <div className={cn("grid gap-x-8 gap-y-6", groups.length > 1 && "sm:grid-cols-2")}>
        {groups.map((group) => {
          const name = group[0]?.groupName ?? null;
          const cut = group[0]?.advance ?? null;
          return (
            <Table className="caption-top table-fixed text-sm" key={group[0]?.groupKey}>
              <caption
                className={cn("text-left", name === null ? "sr-only" : cn(eyebrowClass(), "pb-2"))}
              >
                {name === null
                  ? t("overview.groupTable.title", { stage: stage.name })
                  : groupDisplayName(name, tRoot("common.group"))}
              </caption>
              <TableHeader>
                <TableRow>
                  <TableHead scope="col" className={cn(head, "w-7")}>
                    <span aria-hidden>{t("overview.groupTable.pos")}</span>
                    <span className="sr-only">{t("overview.groupTable.posLabel")}</span>
                  </TableHead>
                  <TableHead scope="col" className={cn(head, "pr-3")}>
                    {t("overview.groupTable.team")}
                  </TableHead>
                  <TableHead scope="col" className={cn(head, "w-[4.5rem]")}>
                    <span aria-hidden>{t("overview.groups.form")}</span>
                    <span className="sr-only">{t("overview.groups.formLabel")}</span>
                  </TableHead>
                  <TableHead scope="col" className={cn(head, "w-12 text-right")}>
                    <span aria-hidden>{t("overview.groups.maps")}</span>
                    <span className="sr-only">{t("overview.groups.mapsLabel")}</span>
                  </TableHead>
                  <TableHead scope="col" className={cn(head, "w-12 text-right")}>
                    {t("overview.groupTable.points")}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {group.map((row) => {
                  const through = cut !== null && row.position <= cut;
                  const teamName = row.team?.name ?? tRoot("common.tbd");
                  return (
                    <TableRow
                      key={row.teamId}
                      className={cn(
                        cut !== null &&
                          row.position === cut &&
                          cut < group.length &&
                          "border-b-[color:var(--aqt-teal)]"
                      )}
                    >
                      <TableCell
                        className={cn(
                          cell,
                          "aqt-tnum",
                          through
                            ? "font-semibold text-[color:var(--aqt-teal)]"
                            : "text-[color:var(--aqt-fg-dim)]"
                        )}
                      >
                        {row.position}
                      </TableCell>
                      <TableCell className={cn(cell, "pr-3")}>
                        {/* The logo's slot is kept when there is none, so every name starts on one line. */}
                        <span className="flex min-w-0 items-center gap-2">
                          <span className="flex size-4 shrink-0">
                            {row.team ? <TeamLogo team={row.team} size="xs" /> : null}
                          </span>
                          <span className="min-w-0 truncate font-medium" title={teamName}>
                            {teamName}
                          </span>
                        </span>
                      </TableCell>
                      <TableCell className={cell}>
                        <span className="flex gap-1">
                          {row.form.slice(-3).map((result, index) => (
                            <ResTag
                              key={index}
                              kind={result}
                              aria-label={t(`result.word.${result}`)}
                            >
                              {t(`result.letter.${result}`)}
                            </ResTag>
                          ))}
                        </span>
                      </TableCell>
                      <TableCell
                        className={cn(cell, "aqt-tnum text-right text-[color:var(--aqt-fg-muted)]")}
                      >
                        {row.mapDiff > 0
                          ? `+${row.mapDiff}`
                          : row.mapDiff < 0
                            ? `−${-row.mapDiff}`
                            : "0"}
                      </TableCell>
                      <TableCell className={cn(cell, "aqt-tnum text-right font-semibold")}>
                        {fraction ? row.points.toFixed(1) : row.points}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          );
        })}
      </div>
      {advance ? (
        <p className="mt-4 flex items-center gap-2 text-label text-[color:var(--aqt-fg-dim)]">
          <span aria-hidden className="h-0.5 w-4 rounded-full bg-[color:var(--aqt-teal)]" />
          {t("overview.groups.advance", { count: advance })}
        </p>
      ) : null}
    </OverviewSection>
  );
}

/**
 * While matches are played: the viewer's next match, what is on now, the stage being played (its group tables, its
 * bracket or its FFA lobbies) and the bans so far.
 */
export function OverviewLiveView({
  tournament,
  slug,
  encounters,
  stage,
  stageEncounters,
  stageStandings,
  miniBracket,
  ffaTable,
  presenter,
  aboutCard,
  formatCard,
  linksCard,
  phasesCard
}: Readonly<{
  tournament: Tournament;
  slug: string;
  encounters: readonly Encounter[];
  stage: StageSummary | null;
  stageEncounters: readonly Encounter[];
  stageStandings: readonly Standings[];
  miniBracket: React.ReactNode;
  ffaTable: React.ReactNode;
  presenter: OverviewMatchPresenter;
  aboutCard: React.ReactNode;
  formatCard: React.ReactNode;
  linksCard: React.ReactNode;
  phasesCard: React.ReactNode;
}>) {
  const t = useTranslations("tournamentDetail");
  const overviewHref = `/tournaments/${slug}`;
  const insights = useTournamentInsights(tournament);
  const roster = useTournamentRoster(tournament);
  const viewerId = useViewerUserId((id) => roster.byUser.has(id));
  const ontology =
    useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;
  const heroes = useHeroCatalog(tournament.discipline);

  const live = encounters.filter(isEncounterLive);
  const recent = encounters
    .filter(isEncounterCompleted)
    .sort((a, b) => String(b.played_at).localeCompare(String(a.played_at)))
    .slice(0, 6);
  const bans = useMemo(
    () => aggregateBans(insights.heroBans, insights.mapBans),
    [insights.heroBans, insights.mapBans]
  );
  const isBracket = stage !== null && ELIMINATION_TYPES[stage.stage_type] === true;
  const groupRows = useMemo(
    () =>
      stage !== null && GROUP_TYPES[stage.stage_type] === true
        ? buildGroupRows(stage, stageStandings, stageEncounters)
        : [],
    [stage, stageStandings, stageEncounters]
  );

  // A whole Swiss round on at once is a board of its own: full width above. The reference always closes the page full
  // width, and with a group table the latest results join it there: the table alone matches the side column, so the
  // two columns end together.
  const wideNow = live.length > 4;
  const nowSection =
    live.length > 0 ? (
      <OverviewSection
        title={t("overview.live.now")}
        action={
          <SectionLink href={`${overviewHref}/matches`}>
            {t("overview.live.allMatches")}
          </SectionLink>
        }
      >
        <div className={cn("grid gap-2 sm:grid-cols-2", wideNow && "xl:grid-cols-3")}>
          {live.map((encounter) => (
            <MatchCard
              key={encounter.id}
              encounter={encounter}
              eyebrow={presenter.eyebrowOf(encounter)}
              href={presenter.bracketHref(encounter)}
              streamsCount={presenter.streamsCountOf(encounter)}
            />
          ))}
        </div>
      </OverviewSection>
    ) : null;
  const recentSection =
    recent.length > 0 ? (
      <OverviewSection
        title={t("overview.live.recent")}
        action={
          <SectionLink href={`${overviewHref}/matches`}>
            {t("overview.live.allMatches")}
          </SectionLink>
        }
      >
        <div>
          {recent.map((encounter) => (
            <MatchRow
              key={encounter.id}
              encounter={encounter}
              leading={presenter.encounterRound(encounter)}
              trailing={encounter.best_of ? `Bo${encounter.best_of}` : undefined}
              bracketHref={presenter.bracketHref(encounter)}
              returnTo={overviewHref}
            />
          ))}
        </div>
      </OverviewSection>
    ) : null;

  return (
    <div className="grid min-w-0 gap-4">
      {viewerId ? (
        <MyLiveCard
          viewerId={viewerId}
          roster={roster}
          encounters={encounters}
          groupRows={groupRows}
          ontology={ontology}
          presenter={presenter}
        />
      ) : null}
      {wideNow ? nowSection : null}
      <CardColumns
        main={
          <>
            {wideNow ? null : nowSection}
            {isBracket ? miniBracket : null}
            {stage && groupRows.length > 0 ? (
              <GroupTablesCard stage={stage} rows={groupRows} overviewHref={overviewHref} />
            ) : null}
            {ffaTable}
            {isBracket ? recentSection : null}
          </>
        }
        side={
          <>
            <LiveNumbersCard
              encounters={encounters}
              stageEncounters={stageEncounters}
              heroBans={bans?.totalHeroBans ?? 0}
            />
            {bans ? (
              <BansCard
                bans={bans}
                heroes={heroes}
                roster={roster}
                overviewHref={overviewHref}
                title={t("overview.live.bansSoFar")}
              />
            ) : null}
            {phasesCard}
          </>
        }
      />
      {isBracket ? null : recentSection}
      <AboutTournamentCard aboutCard={aboutCard} formatCard={formatCard} linksCard={linksCard} />
    </div>
  );
}

function LiveNumbersCard({
  encounters,
  stageEncounters,
  heroBans
}: Readonly<{
  encounters: readonly Encounter[];
  stageEncounters: readonly Encounter[];
  heroBans: number;
}>) {
  const t = useTranslations("tournamentDetail");
  const format = useFormatter();
  const done = encounters.filter(isEncounterCompleted);
  const stageDone = stageEncounters.filter(isEncounterCompleted).length;
  const maps = done.reduce(
    (sum, encounter) => sum + encounter.teams.reduce((s, seat) => s + seat.score, 0),
    0
  );
  return (
    <OverviewSection title={t("overview.live.numbers")}>
      <div className="grid grid-cols-2 gap-x-6 gap-y-5">
        <ProfileStat
          label={t("overview.live.stagePlayed")}
          value={stageDone}
          sub={t("common.ofTotal", { total: stageEncounters.length })}
          size="md"
        />
        <ProfileStat label={t("overview.live.matchesPlayed")} value={done.length} size="md" />
        <ProfileStat label={t("overview.live.mapsPlayed")} value={format.number(maps)} size="md" />
        <ProfileStat
          label={t("overview.numbers.heroBans")}
          value={format.number(heroBans)}
          size="md"
        />
      </div>
    </OverviewSection>
  );
}

function MyLiveCard({
  viewerId,
  roster,
  encounters,
  groupRows,
  ontology,
  presenter
}: Readonly<{
  viewerId: number;
  roster: TournamentRoster;
  encounters: readonly Encounter[];
  groupRows: readonly GroupRow[];
  ontology: RoleOntology | null;
  presenter: OverviewMatchPresenter;
}>) {
  const t = useTranslations("tournamentDetail");
  const entry = roster.byUser.get(viewerId);
  if (!entry) return null;
  const { player, team } = entry;
  const mine = encounters.filter((encounter) =>
    encounter.teams.some((seat) => seat.team_id === team.id)
  );
  const played = mine
    .filter(isEncounterCompleted)
    .map((encounter) => ({ encounter, seat: seriesFor(encounter, team.id) }))
    .filter((row): row is { encounter: Encounter; seat: TeamSeries } => row.seat !== null)
    .sort((a, b) => String(a.encounter.played_at).localeCompare(String(b.encounter.played_at)));
  // On now, else the earliest unfinished series whose opponent is known.
  const next =
    mine.find(isEncounterLive) ??
    mine
      .filter(
        (encounter) =>
          !isEncounterCompleted(encounter) &&
          encounter.teams.filter((seat) => seat.team_id != null).length === 2
      )
      .sort((a, b) => a.round - b.round || a.id - b.id)[0] ??
    null;
  const opponent = next?.teams.find((seat) => seat.team_id !== team.id) ?? null;
  const won = played.filter((row) => row.seat.result === "w").length;
  const lost = played.filter((row) => row.seat.result === "l").length;
  const draws = played.length - won - lost;
  const table = groupRows.find((row) => row.teamId === team.id);
  const groupSize = table ? groupRows.filter((row) => row.groupKey === table.groupKey).length : 0;
  const round = presenter.encounterRound;

  return (
    <OverviewSection title={t("overview.my.title")}>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-x-10">
        <div className="grid content-start gap-6">
          <div className="flex min-w-0 items-center gap-3">
            <TeamLogo team={team} size="lg" />
            <div className="min-w-0">
              <p className="truncate font-onest text-heading font-semibold">{team.name}</p>
              <p className="mt-0.5 flex items-center gap-1.5 text-caption text-[color:var(--aqt-fg-muted)]">
                <PlayerRoleIcon role={player.role} ontology={ontology} size={14} decorative />
                {splitHandle(player.name).name}
              </p>
            </div>
          </div>
          <div>
            <div className="flex items-center justify-between gap-3">
              <Eyebrow>{next ? t("overview.live.nextMatch") : t("overview.live.noNext")}</Eyebrow>
              {next && isEncounterLive(next) ? (
                <Badge hue="var(--aqt-status-live)" size="sm">
                  {t("overview.live.onAir")}
                </Badge>
              ) : null}
            </div>
            {next && opponent ? (
              <HoverPrefetchLink
                href={presenter.bracketHref(next)}
                className="mt-2 block transition-colors hover:text-[color:var(--aqt-teal)]"
              >
                <span className="flex items-center gap-2 text-heading font-semibold">
                  {t("overview.live.vs")}
                  <TeamName
                    team={{ name: opponent.name, image_url: opponent.team?.image_url }}
                    size="sm"
                  />
                </span>
                <span className="mt-1 block text-caption text-[color:var(--aqt-fg-muted)]">
                  {round(next)}
                  {next.best_of ? `, Bo${next.best_of}` : ""}
                </span>
              </HoverPrefetchLink>
            ) : (
              <p className="mt-2 text-caption text-[color:var(--aqt-fg-muted)]">
                {t("overview.live.waiting")}
              </p>
            )}
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-5">
            <ProfileStat
              label={t("overview.my.series")}
              value={`${won}–${lost}`}
              sub={t("overview.my.seriesSub", {
                draws,
                won: played.reduce((s, row) => s + row.seat.mine.score, 0),
                lost: played.reduce((s, row) => s + row.seat.theirs.score, 0)
              })}
            />
            {table ? (
              <ProfileStat
                label={t("overview.live.groupPlace")}
                value={`${table.position}`}
                sub={t("common.ofTotal", { total: groupSize })}
              />
            ) : null}
          </div>
        </div>
        <div className="lg:border-l lg:border-[color:var(--aqt-border)] lg:pl-10">
          <Eyebrow as="h3" className="mb-1 block">
            {t("overview.my.matches")}
          </Eyebrow>
          {played.length === 0 ? (
            <p className="py-2 text-caption text-[color:var(--aqt-fg-dim)]">
              {t("overview.live.noneYet")}
            </p>
          ) : (
            <ol className="-mx-2 divide-y divide-[color:var(--aqt-border)]">
              {played.map(({ encounter, seat }) => (
                <li key={encounter.id}>
                  <TeamSeriesRow encounter={encounter} seat={seat} round={round(encounter)} />
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </OverviewSection>
  );
}
