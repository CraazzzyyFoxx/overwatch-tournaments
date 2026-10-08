import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Calendar, Clock, Network, Trophy } from "lucide-react";

import {
  Column,
  ColumnHead,
  EmptyNote,
  Facts,
  Fact,
  Feat,
  FEAT_META_CLASS,
  FEAT_NAME_CLASS,
  LiveDot,
  LoadError,
  MoreLink,
  PlainPill,
  Roster,
  Section,
  SectionHead
} from "@/components/site/open-layout";
import { owtButton } from "@/components/site/owt-button";
import { Skeleton } from "@/components/ui/skeleton";
import { getFormatter } from "@/lib/datetime/server";
import { getPlayerSlug } from "@/lib/player";
import { getFinishedTournaments, type FinishedTournament } from "@/lib/tournament/finished";
import { getTournamentStatusMeta } from "@/lib/tournament/status";
import { tournamentHref } from "@/lib/tournament/url";
import type { Formatter } from "@/lib/datetime";
import type { Tournament } from "@/types/tournament.types";
import type { Workspace } from "@/types/workspace.types";

import { getCommunityTournament, getFirstTournamentYear } from "./community.data";
import { ScopedMoreLink } from "./WorkspaceScopeLink";

const TITLE_ID = "now-title";

/** "июн 2026" — the chronicle's date column. */
function monthYear(format: Formatter, date: Date): string {
  const month = format
    .dateTime(date, { month: "short", timeZone: "UTC" })
    .replace(".", "");
  return `${month} ${format.dateTime(date, { year: "numeric", timeZone: "UTC" })}`;
}

function longDate(format: Formatter, date: Date): string {
  return format.dateTime(date, {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC"
  });
}

/** Section frame: rubric, title and the exit into the community's tournaments. */
async function Shell({
  workspace,
  children
}: Readonly<{ workspace: Workspace; children: React.ReactNode }>) {
  const t = await getTranslations("workspace");
  return (
    <Section id="now" labelledBy={TITLE_ID} closed>
      <SectionHead
        rubric={t("now.rubric")}
        title={t("now.title")}
        titleId={TITLE_ID}
        aside={
          <ScopedMoreLink workspaceId={workspace.id} href="/tournaments">
            {t("allTournaments")}
          </ScopedMoreLink>
        }
      />
      {children}
    </Section>
  );
}

export async function NowInCommunitySkeleton({
  workspace
}: Readonly<{ workspace: Workspace }>) {
  return (
    <Shell workspace={workspace}>
      <div className="grid items-start gap-x-10 gap-y-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="border-t-2 border-[color:var(--aqt-border-3)] pt-5">
          <Skeleton className="h-3 w-28" />
          <Skeleton className="mt-3.5 h-7 w-3/4" />
          <Skeleton className="mt-3 h-4 w-1/2" />
          <div className="mt-6 flex gap-5">
            <Skeleton className="h-10 w-20" />
            <Skeleton className="h-10 w-20" />
            <Skeleton className="h-10 w-20" />
          </div>
        </div>
        <Column>
          <ColumnHead title={<Skeleton className="h-3 w-36" />} />
          <ol>
            {[0, 1, 2, 3, 4].map((row) => (
              <li key={row} className="grid grid-cols-[96px_minmax(0,1fr)] gap-4">
                <Skeleton className="mt-1 h-3 w-16" />
                <div className="border-l border-[color:var(--aqt-border)] pb-[22px] pl-6">
                  <Skeleton className="h-4 w-2/3" />
                  <Skeleton className="mt-2 h-3 w-1/2" />
                  <Skeleton className="mt-2 h-3 w-3/4" />
                </div>
              </li>
            ))}
          </ol>
        </Column>
      </div>
    </Shell>
  );
}

/**
 * What is happening in the community right now — the one tournament worth
 * acting on, with the community's past ones beside it.
 */
export async function NowInCommunity({ workspace }: Readonly<{ workspace: Workspace }>) {
  const t = await getTranslations("workspace");

  let active: Tournament | null = null;
  let finished: FinishedTournament[];
  try {
    [active, finished] = await Promise.all([
      getCommunityTournament(workspace.id),
      getFinishedTournaments({ workspaceId: workspace.id, limit: 6 })
    ]);
  } catch {
    return (
      <Shell workspace={workspace}>
        <LoadError what={t("now.what")} dashed />
      </Shell>
    );
  }

  const lead = active ?? finished[0]?.tournament ?? null;
  const chronicle = finished.filter((row) => row.tournament.id !== lead?.id);

  let firstYear: number | null = null;
  try {
    firstYear = await getFirstTournamentYear(workspace.id);
  } catch {
    // The column keeps its title without the "since" line.
  }

  return (
    <Shell workspace={workspace}>
      <div className="grid items-start gap-x-10 gap-y-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        {active ? (
          <LeadActive tournament={active} />
        ) : finished[0] ? (
          <LeadFinished row={finished[0]} />
        ) : (
          <EmptyNote>{t("now.noTournaments")}</EmptyNote>
        )}
        <Column>
          <ColumnHead
            title={t("now.pastTitle")}
            sub={firstYear === null ? undefined : t("now.pastSince", { year: firstYear })}
          />
          {chronicle.length === 0 ? (
            <EmptyNote>{t("now.noPast")}</EmptyNote>
          ) : (
            <ol className="mt-4">
              {chronicle.map((row, index) => (
                <ChronicleRow
                  key={row.tournament.id}
                  row={row}
                  last={index === chronicle.length - 1}
                />
              ))}
            </ol>
          )}
        </Column>
      </div>
    </Shell>
  );
}

/** The tournament being played, or the one taking entries. */
async function LeadActive({ tournament }: Readonly<{ tournament: Tournament }>) {
  const [t, tCommon, tSite, format] = await Promise.all([
    getTranslations("workspace"),
    getTranslations("common"),
    getTranslations("site"),
    getFormatter()
  ]);
  const live = getTournamentStatusMeta(tournament.status).variant === "live";

  if (live) {
    return (
      <Feat
        tone="live"
        kicker={
          <>
            <LiveDot />
            {t("now.liveKicker")}
          </>
        }
        head={
          <Link href={tournamentHref(tournament)} prefetch={false} className={FEAT_NAME_CLASS}>
            {tournament.name}
          </Link>
        }
      >
        <Facts>
          {tournament.status === "playoffs" ? (
            <Fact value={tCommon("statusBadge.playoffs")} label={t("now.stage")} />
          ) : null}
          {typeof tournament.teams_count === "number" ? (
            <Fact
              value={format.number(tournament.teams_count)}
              label={t("teamsLabel", { count: tournament.teams_count })}
            />
          ) : null}
          {typeof tournament.participants_count === "number" ? (
            <Fact
              value={format.number(tournament.participants_count)}
              label={t("participantsLabel", { count: tournament.participants_count })}
            />
          ) : null}
        </Facts>
        <div className="flex flex-wrap gap-2">
          <Link
            href={tournamentHref(tournament, "/bracket")}
            prefetch={false}
            className={owtButton({ variant: "outline", size: "sm" })}
          >
            <Network aria-hidden />
            {t("now.bracket")}
          </Link>
          <Link
            href={tournamentHref(tournament, "/matches")}
            prefetch={false}
            className={owtButton({ variant: "ghost", size: "sm" })}
          >
            {t("now.matches")}
          </Link>
        </div>
      </Feat>
    );
  }

  const registrationEnd =
    tournament.phase_schedule.find((phase) => phase.status === "registration")?.ends_at ?? null;
  const liveStart =
    tournament.phase_schedule.find((phase) => phase.status === "live")?.starts_at ??
    String(tournament.start_date);
  const time = (value: string) =>
    format.dateTime(new Date(value), {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit"
    });

  return (
    <Feat
      tone="upcoming"
      kicker={
        <>
          <Calendar aria-hidden />
          {t("now.registrationKicker")}
        </>
      }
      head={
        <>
          <Link href={tournamentHref(tournament)} prefetch={false} className={FEAT_NAME_CLASS}>
            {tournament.name}
          </Link>
          {/* Mock wording: a team registration takes team entries, every other
              formation (balancer, draft, solo) takes players one by one. */}
          <div className={FEAT_META_CLASS}>
            {tSite(tournament.team_formation === "registration" ? "entry.team" : "entry.solo")}
          </div>
        </>
      }
    >
      <Facts>
        {registrationEnd ? (
          <Fact
            value={
              <time dateTime={registrationEnd}>
                {t("now.until", { time: time(registrationEnd) })}
              </time>
            }
            label={t("now.acceptingLabel")}
          />
        ) : null}
        <Fact
          value={<time dateTime={liveStart}>{time(liveStart)}</time>}
          label={t("now.startLabel")}
        />
        {typeof tournament.registrations_count === "number" ? (
          <Fact
            value={format.number(tournament.registrations_count)}
            label={t("applicationsLabel", { count: tournament.registrations_count })}
          />
        ) : null}
      </Facts>
      <MoreLink href={tournamentHref(tournament, "/rules")}>{t("now.rulesAndFormat")}</MoreLink>
    </Feat>
  );
}

/** Nothing running: the community's last tournament and who won it. */
async function LeadFinished({ row }: Readonly<{ row: FinishedTournament }>) {
  const [t, format] = await Promise.all([getTranslations("workspace"), getFormatter()]);
  const { tournament, winner } = row;
  const start = new Date(tournament.start_date);

  return (
    <Feat
      tone="past"
      kicker={
        <>
          <Clock aria-hidden />
          {t("now.lastKicker")}
        </>
      }
      head={
        <>
          <Link href={tournamentHref(tournament)} prefetch={false} className={FEAT_NAME_CLASS}>
            {tournament.name}
          </Link>
          <div className={FEAT_META_CLASS}>
            <time dateTime={start.toISOString()} title={longDate(format, start)}>
              {longDate(format, start)}
            </time>
            {typeof tournament.participants_count === "number"
              ? ` · ${t("participants", { count: tournament.participants_count })}`
              : null}
          </div>
          {winner ? (
            <>
              <div className={`${FEAT_META_CLASS} text-[color:var(--aqt-fg)]`}>
                <Trophy aria-hidden /> {t("now.wonBy")}{" "}
                <b className="font-semibold">{winner.team}</b>
              </div>
              <Roster>
                {winner.players.map((player) => (
                  <Link key={player} href={`/users/${getPlayerSlug(player)}`} prefetch={false}>
                    {player}
                  </Link>
                ))}
              </Roster>
            </>
          ) : null}
        </>
      }
    >
      <MoreLink href={tournamentHref(tournament)}>{t("now.results")}</MoreLink>
    </Feat>
  );
}

/** One line of the community's chronicle: when, what, who won it. */
async function ChronicleRow({
  row,
  last
}: Readonly<{ row: FinishedTournament; last: boolean }>) {
  const [t, format] = await Promise.all([getTranslations("workspace"), getFormatter()]);
  const tSite = await getTranslations("site");
  const { tournament, winner } = row;
  const start = new Date(tournament.start_date);

  return (
    <li className="grid grid-cols-[96px_minmax(0,1fr)] gap-4 max-[639px]:grid-cols-1 max-[639px]:gap-1">
      <div className="pt-[3px] font-[family-name:var(--aqt-data)] text-label font-semibold uppercase leading-[1.25] tracking-label text-[color:var(--aqt-fg-faint)] max-[639px]:pl-6">
        <time dateTime={start.toISOString()} title={longDate(format, start)}>
          {monthYear(format, start)}
        </time>
      </div>
      <div
        className={`relative min-w-0 border-l border-[color:var(--aqt-border)] pl-6 ${last ? "pb-1" : "pb-[22px]"}`}
      >
        <span
          aria-hidden
          className="absolute -left-[5px] top-1.5 size-[9px] rounded-full bg-[color:var(--aqt-gold)] shadow-[0_0_0_3px_var(--aqt-bg)]"
        />
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
          <Link
            href={tournamentHref(tournament)}
            prefetch={false}
            className="font-display text-ui font-bold leading-[1.3] text-[color:var(--aqt-fg)] hover:text-[color:var(--aqt-fg-muted)]"
          >
            {tournament.name}
          </Link>
          {tournament.is_league ? <PlainPill>{tSite("league")}</PlainPill> : null}
        </div>
        {winner ? (
          <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3.5 gap-y-1 text-caption text-[color:var(--aqt-fg-muted)]">
            <span>
              <Trophy
                className="inline size-3.5 -translate-y-px text-[color:var(--aqt-gold)]"
                aria-hidden
              />{" "}
              {t("now.wonBy")} <b className="font-semibold text-[color:var(--aqt-fg)]">{winner.team}</b>
            </span>
            <span className="tabular-nums text-[color:var(--aqt-fg-dim)]">
              {[
                typeof tournament.participants_count === "number"
                  ? t("participants", { count: tournament.participants_count })
                  : null,
                typeof tournament.teams_count === "number"
                  ? t("teams", { count: tournament.teams_count })
                  : null
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </div>
        ) : null}
        {winner && winner.players.length > 0 ? (
          <div
            className="mt-1 truncate text-caption text-[color:var(--aqt-fg-dim)]"
            title={winner.players.join(", ")}
          >
            {winner.players.join(" · ")}
          </div>
        ) : null}
      </div>
    </li>
  );
}
