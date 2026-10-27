import { cache } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { getTranslations } from "next-intl/server";

import {
  MoreLink,
  OpenEmptyRow,
  OpenLoadError,
  Section,
  SectionHead
} from "@/components/site/open-layout";
import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import {
  FactsRow,
  GLASS_CLASS,
  IconFact,
  StageBar,
  tournamentFacts
} from "@/components/tournaments/TournamentFacts";
import Image from "@/components/ui/image";
import { Skeleton } from "@/components/ui/skeleton";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { getFormatter } from "@/lib/datetime/server";
import { getActiveTournaments, getPublicWorkspaces } from "@/lib/site/public-data";
import { tournamentPicture } from "@/lib/tournament/art";
import { stageProgress } from "@/lib/tournament/stage-progress";
import { getTournamentStatusMeta } from "@/lib/tournament/status";
import { tournamentHref } from "@/lib/tournament/url";
import { cn } from "@/lib/utils";
import catalogService from "@/services/catalog.service";
import encounterService from "@/services/encounter.service";
import tournamentService from "@/services/tournament.service";
import type { Tournament } from "@/types/tournament.types";
import type { WorkspaceListItem } from "@/types/workspace.types";

const TITLE_ID = "home-now-title";

/**
 * The featured card and the list side by side from `lg`, about 1.55 : 1; stacked below. The single column is
 * `minmax(0,1fr)` too: an implicit `auto` track grows to a fact line's unwrapped width and pushes the page sideways.
 */
const SHOWCASE_COLUMNS = "grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]";

/** A list row: a 16:9 thumbnail beside its lines. */
const ROW_CLASS = "grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-4 p-2 sm:grid-cols-[152px_minmax(0,1fr)]";

/**
 * The featured card's hover and focus: a teal frame and a soft teal glow under
 * it. One `:is()` variant so the two states cannot drift apart. The hero
 * feed's cards glow the same way.
 */
export const FEATURED_GLOW =
  "[&:is(:hover,:focus-visible)]:border-[color:color-mix(in_srgb,var(--aqt-teal)_65%,transparent)] [&:is(:hover,:focus-visible)]:shadow-[0_0_0_1px_color-mix(in_srgb,var(--aqt-teal)_25%,transparent),0_22px_44px_-22px_color-mix(in_srgb,var(--aqt-teal)_55%,transparent)]";

/** The featured tournament, then up to four rows beside it. */
const CARDS = 5;

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
  /** Nothing is active: the block lists finished tournaments only. */
  recent: boolean;
  workspaces: Map<number, WorkspaceListItem>;
  /** The instant the countdowns are measured from: the page is rendered per request. */
  now: number;
}

/** What is running comes first (live, then open), then the newest finished ones fill the block. */
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
    workspaces: new Map(workspaces.map((workspace) => [workspace.id, workspace])),
    now: Date.now()
  };
}

/**
 * What is happening across the platform, as a showcase: the first tournament
 * large, the next four as a list beside it. The page's entrance for a player,
 * kept to one block because the page is the product's, not a community's.
 * Each tournament is drawn with its picture (`lib/tournament/art.ts`, shared
 * with the tournament list): the organizer's cover; where there is none, the
 * map last played in it, or a map of its game before anything is played. With
 * nothing active the block is the latest finished tournaments and says so.
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
        <Showcase data={data} />
      )}
    </Section>
  );
}

function Showcase({ data }: Readonly<{ data: NowData }>) {
  const [featured, ...rest] = data.items;
  const workspaceOf = (item: NowItem) => data.workspaces.get(item.tournament.workspace_id);

  // A lone tournament gets the whole width, at a wider frame so it does not
  // tower over the page.
  if (rest.length === 0) {
    return <FeaturedCard item={featured} workspace={workspaceOf(featured)} now={data.now} wide />;
  }

  return (
    <div className={cn("grid gap-5", SHOWCASE_COLUMNS)}>
      <FeaturedCard item={featured} workspace={workspaceOf(featured)} now={data.now} />
      {/* As tall as the featured card from `lg`, its rows spread over it. */}
      <div className="flex flex-col gap-2 lg:justify-between">
        {rest.map((item) => (
          <ShowcaseRow key={item.tournament.id} item={item} workspace={workspaceOf(item)} now={data.now} />
        ))}
      </div>
    </div>
  );
}

/**
 * The first tournament, large: its picture behind its community, name, stage
 * and facts. One link; the "Open tournament" pill that fades in under the
 * pointer is text inside it, not a second control.
 */
async function FeaturedCard({
  item,
  workspace,
  now,
  wide = false
}: Readonly<{ item: NowItem; workspace: WorkspaceListItem | undefined; now: number; wide?: boolean }>) {
  const [t, format] = await Promise.all([getTranslations(), getFormatter()]);
  const { tournament, picture } = item;
  const variant = getTournamentStatusMeta(tournament.status).variant;

  return (
    <Link
      href={tournamentHref(tournament)}
      prefetch={false}
      className={cn(
        // `aspect-video` is a floor, not a clamp: no `overflow-hidden` here, so
        // on a phone the card grows past 16:9 when its lines need the room.
        "group relative flex aspect-video flex-col justify-end rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] transition-[border-color,box-shadow] duration-300 focus-visible:outline-offset-4",
        FEATURED_GLOW,
        wide && "lg:aspect-[21/9]"
      )}
    >
      {/* The frame clips the picture's zoom; the scrim keeps the lines over it
          readable whatever the artwork. */}
      <span aria-hidden className="absolute inset-0 overflow-hidden rounded-[inherit]">
        {picture ? (
          <Image
            src={picture}
            alt=""
            fill
            sizes={wide ? "100vw" : "(min-width: 1024px) 60vw, 100vw"}
            className="aqt-zoom select-none object-cover"
          />
        ) : null}
        <span className="absolute inset-0 bg-gradient-to-b from-transparent from-30% via-[color:color-mix(in_srgb,var(--aqt-bg)_55%,transparent)] via-60% to-[color:color-mix(in_srgb,var(--aqt-bg)_95%,transparent)]" />
      </span>

      {/* A finished tournament carries no status: "Finished" says nothing a
          date range does not. */}
      {variant === "finished" ? null : (
        <span className={cn(GLASS_CLASS, "absolute left-4 top-4 sm:left-5 sm:top-5")}>
          <TournamentStatusPill status={variant}>{t(`common.statusBadge.${tournament.status}`)}</TournamentStatusPill>
        </span>
      )}

      {/* `pt-16` keeps the pill clear once a phone grows the card; `lg:pr-52`
          keeps the lines clear of the pill fading in bottom-right. */}
      <span className="relative flex flex-col items-start gap-3 p-5 pt-16 lg:px-7 lg:py-6 lg:pr-52">
        {workspace ? (
          <span className="flex max-w-full items-center gap-2 text-caption text-[color:var(--aqt-fg-muted)]">
            <WorkspaceAvatar workspace={workspace} size={22} />
            <span className="truncate">{workspace.name}</span>
          </span>
        ) : null}
        <b className="max-w-full text-balance font-display text-title font-extrabold text-[color:var(--aqt-fg)] lg:text-headline">
          {tournament.name}
        </b>
        {variant === "live" ? <StageBar stage={stageProgress(tournament, tournament.status, t)} /> : null}
        <FactsRow facts={tournamentFacts(tournament, t, format, now)} />
      </span>

      <span
        aria-hidden
        className="pointer-events-none absolute bottom-6 right-6 hidden h-10 translate-y-1.5 items-center gap-2 rounded-lg border border-[color:color-mix(in_srgb,var(--aqt-fg)_14%,transparent)] bg-[color:var(--aqt-overlay-4)] px-4 text-body font-semibold text-[color:var(--aqt-fg)] opacity-0 backdrop-blur-sm transition-[opacity,translate] duration-200 group-hover:translate-y-0 group-hover:opacity-100 group-focus-visible:translate-y-0 group-focus-visible:opacity-100 lg:inline-flex"
      >
        {t("home.now.open")}
        <ArrowRight className="size-4" />
      </span>
    </Link>
  );
}

/**
 * One more tournament: a thumbnail, its status while it runs, its name, then
 * its community and one fact — how far off it is before play, its dates after.
 */
async function ShowcaseRow({
  item,
  workspace,
  now
}: Readonly<{ item: NowItem; workspace: WorkspaceListItem | undefined; now: number }>) {
  const [t, format] = await Promise.all([getTranslations(), getFormatter()]);
  const { tournament, picture } = item;
  const variant = getTournamentStatusMeta(tournament.status).variant;
  const facts = tournamentFacts(tournament, t, format, now);
  const fact = facts.find((candidate) => candidate.kind === "countdown") ?? facts[0];

  return (
    <Link
      href={tournamentHref(tournament)}
      prefetch={false}
      className={cn(
        ROW_CLASS,
        "group rounded-[14px] border border-transparent transition-colors duration-200 hover:border-[color:var(--aqt-border)] hover:bg-[color:var(--aqt-overlay-3)] focus-visible:outline-offset-2"
      )}
    >
      <span className="relative aspect-video overflow-hidden rounded-lg bg-[color:var(--aqt-bg-2)]">
        {picture ? (
          <Image
            src={picture}
            alt=""
            fill
            sizes="(min-width: 640px) 152px, 120px"
            className="aqt-zoom select-none object-cover"
          />
        ) : null}
      </span>
      <span className="flex min-w-0 flex-col items-start gap-1.5">
        {variant === "finished" ? null : (
          <TournamentStatusPill status={variant}>{t(`common.statusBadge.${tournament.status}`)}</TournamentStatusPill>
        )}
        <b className="line-clamp-2 font-display text-ui font-semibold leading-tight text-[color:var(--aqt-fg)]">
          {tournament.name}
        </b>
        {/* Wraps rather than truncates: on a phone the date drops under the community instead of losing its end.
            The fact's icon already separates the two, so no middle dot. */}
        <span className="flex max-w-full flex-wrap items-center gap-x-3 gap-y-1 text-caption text-[color:var(--aqt-fg-muted)]">
          {workspace ? (
            <span className="inline-flex min-w-0 max-w-full items-center gap-2">
              <WorkspaceAvatar workspace={workspace} size={18} />
              <span className="truncate">{workspace.name}</span>
            </span>
          ) : null}
          <IconFact fact={fact} />
        </span>
      </span>
    </Link>
  );
}

/** The loaded block's shape: the head, the featured card and four rows. */
export function NowSkeleton() {
  return (
    <Section id="now" labelledBy={TITLE_ID}>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <Skeleton className="h-7 w-56" />
        <Skeleton className="h-11 w-28" />
      </div>
      <div className={cn("grid gap-5", SHOWCASE_COLUMNS)}>
        <Skeleton className="aspect-video w-full rounded-2xl" />
        <div className="flex flex-col gap-2 lg:justify-between">
          {Array.from({ length: CARDS - 1 }).map((_, index) => (
            <div key={index} className={ROW_CLASS}>
              <Skeleton className="aspect-video w-full rounded-lg" />
              <div className="flex flex-col gap-2">
                <Skeleton className="h-5 w-4/5" />
                <Skeleton className="h-4 w-36" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </Section>
  );
}
