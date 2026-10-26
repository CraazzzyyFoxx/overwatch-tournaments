import { cache } from "react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import {
  MoreLink,
  OpenEmptyRow,
  OpenLoadError,
  Section,
  SectionHead
} from "@/components/site/open-layout";
import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import Image from "@/components/ui/image";
import { Skeleton } from "@/components/ui/skeleton";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { getFormatter } from "@/lib/datetime/server";
import { getActiveTournaments, getPublicWorkspaces } from "@/lib/site/public-data";
import { tournamentPicture } from "@/lib/tournament/art";
import { getTournamentStatusMeta } from "@/lib/tournament/status";
import { tournamentHref } from "@/lib/tournament/url";
import catalogService from "@/services/catalog.service";
import encounterService from "@/services/encounter.service";
import tournamentService from "@/services/tournament.service";
import type { Tournament } from "@/types/tournament.types";
import type { WorkspaceListItem } from "@/types/workspace.types";

const TITLE_ID = "home-now-title";

/** One row: four across from 1100px, two from 640px, one card per line on a phone. */
const ROW_CLASS = "grid grid-cols-1 gap-x-8 gap-y-5 min-[640px]:grid-cols-2 min-[640px]:gap-y-7 min-[1100px]:grid-cols-4";

/** A card: a line beside a 4:3 thumbnail on a phone, the 16:9 picture on top from 640px. */
const CARD_CLASS =
  "group grid min-w-0 grid-cols-[7.5rem_minmax(0,1fr)] items-start gap-x-3.5 focus-visible:outline-offset-4 min-[640px]:grid-cols-1 min-[640px]:gap-y-3";

/** The card's frame turns teal under the pointer (DESIGN §5, a whole-card link); the picture lights up inside it. */
const ART_CLASS =
  "relative aspect-[4/3] overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] transition-colors duration-150 group-hover:border-[color:var(--aqt-teal)] min-[640px]:aspect-[16/9]";

const CARDS = 4;

const SHORT_DATE = { day: "numeric", month: "short" } as const;
const LONG_DATE = { day: "numeric", month: "long", year: "numeric" } as const;

interface NowItem {
  tournament: Tournament;
  /** `tournamentPicture`: the cover, the map last played in it, a map of its game. */
  picture: string | null;
}

/** One game's maps, read once per render and held for a day: the catalog changes with a release. */
const gameMaps = cache(async (discipline: string) => {
  const page = await catalogService
    .list(discipline, "map", { per_page: -1 }, { next: { revalidate: 86_400 } })
    .catch(() => null);
  return page?.results ?? [];
});

/** A card's picture; a covered tournament reads nothing for it. A failed read counts as nothing to draw from. */
async function pictureOf(tournament: Tournament): Promise<string | null> {
  if (tournament.cover_image_url) return tournament.cover_image_url;
  const [latest, catalog] = await Promise.all([
    encounterService.getLatestPlayed(tournament, { next: { revalidate: 300 } }).catch(() => null),
    gameMaps(tournament.discipline)
  ]);
  return tournamentPicture(tournament, latest, catalog) ?? null;
}

interface NowData {
  items: NowItem[];
  /** Nothing is active: the row lists finished tournaments only. */
  recent: boolean;
  workspaces: Map<number, WorkspaceListItem>;
}

/** What is running comes first (live, then open), then the newest finished ones fill the row. */
async function loadNow(): Promise<NowData> {
  const [activePage, workspaces, finished] = await Promise.all([
    getActiveTournaments(),
    getPublicWorkspaces(),
    tournamentService.listTournaments({
      workspaceId: "all",
      status: "completed",
      sort: "start_date",
      order: "desc",
      perPage: CARDS
    })
  ]);

  // Running tournaments only (the read filters by status server-side), live ones first.
  const active = [...activePage.results].sort(
    (left, right) =>
      Number(getTournamentStatusMeta(right.status).variant === "live") -
      Number(getTournamentStatusMeta(left.status).variant === "live")
  );
  // The archive read and the active list can name the same tournament the
  // moment one finishes: never list it twice.
  const done = finished.results.filter(
    (tournament) => !active.some((running) => running.id === tournament.id)
  );
  const shown = [...active, ...done].slice(0, CARDS);

  return {
    items: await Promise.all(
      shown.map(async (tournament) => ({ tournament, picture: await pictureOf(tournament) }))
    ),
    recent: active.length === 0,
    workspaces: new Map(workspaces.map((workspace) => [workspace.id, workspace]))
  };
}

/**
 * What is happening across the platform, as one row of four: the page's
 * entrance for a player, kept to a row because the page is the product's, not
 * a community's. Each tournament is drawn with its picture
 * (`lib/tournament/art.ts`, shared with the tournament list): the organizer's
 * cover; where there is none, the map last played in it, or a map of its game
 * before anything is played. With nothing active the row is the latest
 * finished tournaments and says so.
 */
export async function NowOnPlatform() {
  const t = await getTranslations("home.now");

  let data: NowData | null = null;
  try {
    data = await loadNow();
  } catch {
    data = null;
  }

  return (
    <Section id="now" labelledBy={TITLE_ID}>
      <SectionHead
        title={t(data?.recent ? "titleRecent" : "title")}
        titleId={TITLE_ID}
        aside={<MoreLink href="/tournaments" className="min-h-11">{t("more")}</MoreLink>}
      />
      {data === null ? (
        <OpenLoadError what={t("error")} dashed />
      ) : data.items.length === 0 ? (
        <OpenEmptyRow>{t("emptyBody")}</OpenEmptyRow>
      ) : (
        <div className={ROW_CLASS}>
          {data.items.map((item) => (
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

/** One tournament: its picture, its name, then its community and dates. */
async function TCard({
  item,
  workspace
}: Readonly<{ item: NowItem; workspace: WorkspaceListItem | undefined }>) {
  const [statusLabel, format] = await Promise.all([
    getTranslations("common.statusBadge"),
    getFormatter()
  ]);
  const { tournament, picture } = item;
  const variant = getTournamentStatusMeta(tournament.status).variant;
  const finished = variant === "finished";
  const start = new Date(tournament.start_date);
  const end = new Date(tournament.end_date);

  return (
    <Link href={tournamentHref(tournament)} prefetch={false} className={CARD_CLASS}>
      <div className={ART_CLASS}>
        {picture ? (
          // `alt=""`: the name beside it carries every fact the picture does.
          <Image
            src={picture}
            alt=""
            fill
            sizes="(min-width: 1100px) 300px, (min-width: 640px) 46vw, 120px"
            className="select-none object-cover opacity-85 transition-opacity duration-150 group-hover:opacity-100"
          />
        ) : null}
        {/* A finished card carries no status: a row of "Finished" says
            nothing. The opaque backing is what the pill's tint needs over a
            picture. */}
        {finished ? null : (
          <span className="absolute left-2 top-2 flex rounded-md bg-[color:var(--aqt-bg)]">
            <TournamentStatusPill status={variant}>{statusLabel(tournament.status)}</TournamentStatusPill>
          </span>
        )}
      </div>
      <div className="flex min-w-0 flex-col gap-1.5">
        <b className="line-clamp-2 font-display text-ui font-semibold leading-[1.3] text-[color:var(--aqt-fg)]">
          {tournament.name}
        </b>
        <span className="flex max-w-full items-center gap-2 text-caption text-[color:var(--aqt-fg-muted)]">
          {workspace ? (
            <>
              <WorkspaceAvatar workspace={workspace} size={20} />
              <span className="truncate">{workspace.name}</span>
              <span aria-hidden>·</span>
            </>
          ) : null}
          <time
            dateTime={start.toISOString()}
            title={
              finished ? format.dateTimeRange(start, end, LONG_DATE) : format.dateTime(start, LONG_DATE)
            }
            className="shrink-0"
          >
            {finished ? format.dateTimeRange(start, end, SHORT_DATE) : format.dateTime(start, SHORT_DATE)}
          </time>
        </span>
      </div>
    </Link>
  );
}

/** The loaded row's shape: the head, then four cards. */
export function NowSkeleton() {
  return (
    <Section id="now" labelledBy={TITLE_ID}>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <Skeleton className="h-7 w-56" />
        <Skeleton className="h-11 w-28" />
      </div>
      <div className={ROW_CLASS}>
        {Array.from({ length: CARDS }).map((_, index) => (
          <div
            key={index}
            className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-start gap-x-3.5 min-[640px]:grid-cols-1 min-[640px]:gap-y-3"
          >
            <Skeleton className="aspect-[4/3] w-full rounded-xl min-[640px]:aspect-[16/9]" />
            <div className="flex flex-col gap-2">
              <Skeleton className="h-5 w-4/5" />
              <Skeleton className="h-4 w-36" />
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}
