import type { ReactNode } from "react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Calendar, Clock, Network, Trophy } from "lucide-react";

import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import {
  EYEBROW_CLASS,
  EmptyNote,
  Fact,
  Facts,
  Feat,
  FEAT_META_CLASS,
  FEAT_NAME_CLASS,
  LiveDot,
  LoadError,
  MoreLink,
  Roster,
  Section,
  SectionHead
} from "@/components/site/open-layout";
import { owtButton } from "@/components/site/owt-button";
import { Skeleton } from "@/components/ui/skeleton";
import { getFormatter } from "@/lib/datetime/server";
import { getPlayerSlug } from "@/lib/player";
import { getFinishedTournaments, type FinishedTournament } from "@/lib/tournament/finished";
import { getTournamentStatusMeta, isTournamentStatusActive } from "@/lib/tournament/status";
import { tournamentHref } from "@/lib/tournament/url";
import tournamentService from "@/services/tournament.service";
import workspaceService from "@/services/workspace.service";
import { cn } from "@/lib/utils";
import type { Tournament } from "@/types/tournament.types";
import type { Workspace } from "@/types/workspace.types";

const TITLE_ID = "home-now-title";

/** Mock `.feat__ws`: the community line under the lead tournament's name. */
const FEAT_WS_CLASS = "mt-2 flex items-center gap-2 text-caption text-[color:var(--aqt-fg-muted)]";

/** The lead spans two rows beside the small items, full width below 1100px. */
const FEAT_SPAN = "max-[1099px]:col-span-full min-[1100px]:row-span-2";

const BENTO_CLASS =
  "grid grid-cols-1 gap-x-8 gap-y-7 min-[640px]:grid-cols-2 min-[1100px]:grid-cols-[minmax(0,1.25fr)_repeat(2,minmax(0,1fr))]";

/** The statuses that mean "you can still get in" (mock `isReg`). */
const OPEN_STATUSES = ["registration", "check_in", "announcement"];

// The mock's `fmt.date` / `dateLong` / `dateTime`, as option sets rather than
// wrappers — the visible value is short, the `title` beside it is absolute.
const SHORT_DATE = { day: "numeric", month: "short" } as const;
const LONG_DATE = { day: "numeric", month: "long", year: "numeric" } as const;
const SHORT_DATE_TIME = { ...SHORT_DATE, hour: "2-digit", minute: "2-digit" } as const;
const LONG_DATE_TIME = { ...LONG_DATE, hour: "2-digit", minute: "2-digit" } as const;

interface NowItem {
  tournament: Tournament;
  winner: FinishedTournament["winner"];
}

interface NowData {
  /** The running tournament, else the first open registration. */
  lead: Tournament | null;
  /** Nothing active: the most recent finished tournament takes the big slot. */
  last: FinishedTournament | null;
  small: NowItem[];
  workspaces: Map<number, Workspace>;
}

async function loadNow(): Promise<NowData> {
  const [activePage, workspaces, finished] = await Promise.all([
    tournamentService.getActive({ skipWorkspace: true }),
    workspaceService.getAll("public"),
    getFinishedTournaments({ workspaceId: "all", limit: 5 })
  ]);

  const active = activePage.results.filter((tournament) =>
    isTournamentStatusActive(tournament.status)
  );
  // The archive read and the active list can name the same tournament the
  // moment one finishes: never list it twice.
  const done = finished.filter(
    (entry) => !active.some((tournament) => tournament.id === entry.tournament.id)
  );

  const lead =
    active.find((tournament) => getTournamentStatusMeta(tournament.status).variant === "live") ??
    active.find((tournament) => OPEN_STATUSES.includes(tournament.status)) ??
    null;
  const big = lead ?? done[0]?.tournament ?? null;

  return {
    lead,
    last: lead ? null : (done[0] ?? null),
    small: [
      ...active.map((tournament) => ({ tournament, winner: null })),
      ...done.map((entry) => ({ tournament: entry.tournament, winner: entry.winner }))
    ]
      .filter((item) => item.tournament.id !== big?.id)
      .slice(0, 4),
    workspaces: new Map(workspaces.map((workspace) => [workspace.id, workspace]))
  };
}

/** What is happening across the platform right now — the page's lead block. */
export async function NowOnPlatform() {
  const t = await getTranslations("home.now");

  let data: NowData | null = null;
  try {
    data = await loadNow();
  } catch {
    data = null;
  }

  return (
    <Section id="now" labelledBy={TITLE_ID} closed>
      <SectionHead
        rubric={t("rubric")}
        title={t("title")}
        titleId={TITLE_ID}
        aside={<MoreLink href="/tournaments">{t("more")}</MoreLink>}
      />
      {data === null ? (
        <LoadError what={t("error")} dashed />
      ) : !data.lead && !data.last && data.small.length === 0 ? (
        <EmptyNote>{t("emptyBody")}</EmptyNote>
      ) : (
        <div className={BENTO_CLASS}>
          {data.lead ? (
            <LeadFeat
              tournament={data.lead}
              workspace={data.workspaces.get(data.lead.workspace_id)}
            />
          ) : data.last ? (
            <LastFinishedFeat
              entry={data.last}
              workspace={data.workspaces.get(data.last.tournament.workspace_id)}
            />
          ) : null}
          {data.small.map((item) => (
            <TCard
              key={item.tournament.id}
              item={item}
              workspace={data.workspaces.get(item.tournament.workspace_id)}
            />
          ))}
        </div>
      )}
    </Section>
  );
}

function WorkspaceLine({
  workspace,
  children
}: Readonly<{ workspace: Workspace | undefined; children?: ReactNode }>) {
  if (!workspace) return null;
  return (
    <div className={FEAT_WS_CLASS}>
      <WorkspaceAvatar workspace={workspace} size={20} />
      {workspace.name}
      {children}
    </div>
  );
}

/** The running tournament, or the open registration when nothing is running. */
async function LeadFeat({
  tournament,
  workspace
}: Readonly<{ tournament: Tournament; workspace: Workspace | undefined }>) {
  const [t, tSite, statusLabel, format] = await Promise.all([
    getTranslations("home.now"),
    getTranslations("site"),
    getTranslations("common.statusBadge"),
    getFormatter()
  ]);
  const name = (
    <Link
      href={tournamentHref(tournament)}
      prefetch={false}
      className={cn(FEAT_NAME_CLASS, "block")}
    >
      {tournament.name}
    </Link>
  );

  if (getTournamentStatusMeta(tournament.status).variant === "live") {
    return (
      <Feat
        tone="live"
        className={FEAT_SPAN}
        kicker={
          <>
            <LiveDot />
            {t("live")}
          </>
        }
        head={
          <>
            {name}
            <WorkspaceLine workspace={workspace} />
          </>
        }
      >
        <Facts>
          {tournament.status === "playoffs" ? (
            <Fact value={statusLabel("playoffs")} label={t("stage")} />
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
            {t("bracket")}
          </Link>
          <Link
            href={tournamentHref(tournament, "/matches")}
            prefetch={false}
            className={owtButton({ variant: "ghost", size: "sm" })}
          >
            {t("matches")}
          </Link>
        </div>
      </Feat>
    );
  }

  const registrationEnd = tournament.phase_schedule?.find(
    (phase) => phase.status === "registration"
  )?.ends_at;
  const start = new Date(
    tournament.phase_schedule?.find((phase) => phase.status === "live")?.starts_at ??
      tournament.start_date
  );

  return (
    <Feat
      tone="upcoming"
      className={FEAT_SPAN}
      kicker={
        <>
          <Calendar aria-hidden />
          {t("regOpen")}
        </>
      }
      head={
        <>
          {name}
          <WorkspaceLine workspace={workspace} />
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
              <time
                dateTime={new Date(registrationEnd).toISOString()}
                title={format.dateTime(new Date(registrationEnd), LONG_DATE_TIME)}
              >
                {t("until", {
                  date: format.dateTime(new Date(registrationEnd), SHORT_DATE_TIME)
                })}
              </time>
            }
            label={t("regEnds")}
          />
        ) : null}
        <Fact
          value={
            <time
              dateTime={start.toISOString()}
              title={format.dateTime(start, LONG_DATE_TIME)}
            >
              {format.dateTime(start, SHORT_DATE_TIME)}
            </time>
          }
          label={t("start")}
        />
        {typeof tournament.registrations_count === "number" ? (
          <Fact
            value={format.number(tournament.registrations_count)}
            label={t("registrationsLabel", { count: tournament.registrations_count })}
          />
        ) : null}
      </Facts>
      {/* Registration opens from a dialog in the tournament page's header rail;
          there is no standalone registration route to deep-link to. */}
      <div className="flex flex-wrap gap-2">
        <Link
          href={tournamentHref(tournament)}
          prefetch={false}
          className={owtButton({ variant: "outline", size: "sm" })}
        >
          {t("apply")}
        </Link>
        <Link
          href={tournamentHref(tournament)}
          prefetch={false}
          className={owtButton({ variant: "ghost", size: "sm" })}
        >
          {t("about")}
        </Link>
      </div>
    </Feat>
  );
}

/** Nothing is running: the last tournament and its champion, never a blank box. */
async function LastFinishedFeat({
  entry,
  workspace
}: Readonly<{ entry: FinishedTournament; workspace: Workspace | undefined }>) {
  const [t, format] = await Promise.all([getTranslations("home.now"), getFormatter()]);
  const { tournament, winner } = entry;
  const start = new Date(tournament.start_date);

  return (
    <Feat
      tone="past"
      className={FEAT_SPAN}
      kicker={
        <>
          <Clock aria-hidden />
          {t("none")}
        </>
      }
      head={
        <>
          <span className={cn(EYEBROW_CLASS, "mb-2 block")}>{t("lastTournament")}</span>
          <Link
            href={tournamentHref(tournament)}
            prefetch={false}
            className={cn(FEAT_NAME_CLASS, "block")}
          >
            {tournament.name}
          </Link>
          <WorkspaceLine workspace={workspace}>
            <span aria-hidden>·</span>
            <time dateTime={start.toISOString()} title={format.dateTime(start, LONG_DATE)}>
              {format.dateTime(start, SHORT_DATE)}
            </time>
          </WorkspaceLine>
          {winner ? (
            <>
              <div className={cn(FEAT_META_CLASS, "text-[color:var(--aqt-fg)]")}>
                <Trophy aria-hidden />{" "}
                {t.rich("winnerTeam", {
                  team: winner.team,
                  b: (chunks) => <b className="font-semibold">{chunks}</b>
                })}
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
      <MoreLink href="/tournaments">{t("archive")}</MoreLink>
    </Feat>
  );
}

/** One of the four small items under the lead (mock `.tcard`). */
async function TCard({
  item,
  workspace
}: Readonly<{ item: NowItem; workspace: Workspace | undefined }>) {
  const [t, statusLabel, format] = await Promise.all([
    getTranslations("home.now"),
    getTranslations("common.statusBadge"),
    getFormatter()
  ]);
  const { tournament, winner } = item;
  const variant = getTournamentStatusMeta(tournament.status).variant;
  const start = new Date(tournament.start_date);
  const registrationEnd = tournament.phase_schedule?.find(
    (phase) => phase.status === "registration"
  )?.ends_at;

  const startTime = (
    <time dateTime={start.toISOString()} title={format.dateTime(start, LONG_DATE)}>
      {format.dateTime(start, SHORT_DATE)}
    </time>
  );

  let line: ReactNode;
  if (variant === "finished") {
    line = winner ? (
      t.rich("lineFinishedWinner", {
        date: format.dateTime(start, SHORT_DATE),
        team: winner.team,
        d: () => startTime,
        b: (chunks) => <b className="font-semibold text-[color:var(--aqt-fg)]">{chunks}</b>
      })
    ) : (
      startTime
    );
  } else if (OPEN_STATUSES.includes(tournament.status)) {
    line = [
      registrationEnd
        ? t("applicationsUntil", {
            date: format.dateTime(new Date(registrationEnd), SHORT_DATE)
          })
        : null,
      typeof tournament.registrations_count === "number"
        ? t("registrationsCount", { count: tournament.registrations_count })
        : null
    ]
      .filter(Boolean)
      .join(" · ");
  } else {
    line = [
      typeof tournament.teams_count === "number"
        ? t("teamsCount", { count: tournament.teams_count })
        : null,
      typeof tournament.participants_count === "number"
        ? t("participantsCount", { count: tournament.participants_count })
        : null
    ]
      .filter(Boolean)
      .join(" · ");
  }

  return (
    <Link
      href={tournamentHref(tournament)}
      prefetch={false}
      className="flex min-w-0 flex-col items-start gap-2.5 border-t border-[color:var(--aqt-border-3)] pt-4 transition-colors duration-150 hover:border-t-[color:var(--aqt-teal)] focus-visible:outline-offset-4"
    >
      <TournamentStatusPill status={variant}>{statusLabel(tournament.status)}</TournamentStatusPill>
      <b className="line-clamp-2 font-display text-ui font-bold leading-[1.3] text-[color:var(--aqt-fg)]">
        {tournament.name}
      </b>
      {workspace ? (
        <span className="flex max-w-full items-center gap-2 text-caption text-[color:var(--aqt-fg-muted)]">
          <WorkspaceAvatar workspace={workspace} size={20} />
          <span className="truncate">{workspace.name}</span>
        </span>
      ) : null}
      <span className="mt-auto text-caption text-[color:var(--aqt-fg-dim)]">{line}</span>
    </Link>
  );
}

/** Same bento as the loaded block: one tall lead, four short items. */
export function NowSkeleton() {
  return (
    <Section id="now" labelledBy={TITLE_ID} closed>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div>
          <Skeleton className="h-3 w-20" />
          <Skeleton className="mt-2 h-7 w-56" />
        </div>
        <Skeleton className="h-4 w-28" />
      </div>
      <div className={BENTO_CLASS}>
        <div className={cn(FEAT_SPAN, "border-t-2 border-[color:var(--aqt-border-3)] pt-5")}>
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-3.5 h-8 w-4/5" />
          <Skeleton className="mt-2 h-4 w-40" />
          <div className="mt-[22px] flex gap-[22px]">
            <Skeleton className="h-9 w-20" />
            <Skeleton className="h-9 w-20" />
          </div>
          <div className="mt-[22px] flex gap-2">
            <Skeleton className="h-8 w-24" />
            <Skeleton className="h-8 w-20" />
          </div>
        </div>
        {Array.from({ length: 4 }).map((_, index) => (
          <div
            key={index}
            className="flex flex-col items-start gap-2.5 border-t border-[color:var(--aqt-border-3)] pt-4"
          >
            <Skeleton className="h-[26px] w-20" />
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-4 w-36" />
          </div>
        ))}
      </div>
    </Section>
  );
}
