"use client";

import React from "react";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { usePathname } from "next/navigation";
import { ExternalLink } from "lucide-react";

import TournamentBroadcastDock from "./TournamentBroadcastDock";
import { TOURNAMENT_ACTION_CLASS } from "./tournamentActionClass";
import TournamentRegisterButton from "./TournamentRegisterButton";
import { NextPhaseChip } from "./NextPhaseChip";
import {
  areStreamsVisible,
  getTournamentStatusMeta,
  isTournamentStatusEnded,
} from "@/lib/tournament/status";
import { reachedAtLeast } from "@/lib/tournament/lifecycle";
import { formatDateRange } from "@/lib/datetime";
import { useFormatter } from "@/lib/datetime/client";
import { useInvalidation } from "@/hooks/useInvalidation";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { useEntityWorkspace } from "@/hooks/useEntityWorkspace";
import { useTournamentStreamsQuery } from "../_hooks/useTournamentStreams";
import type { Tournament } from "@/types/tournament.types";

import { useTranslations } from "next-intl";
import TournamentSectionNav from "./TournamentSectionNav";
import { collapsedRailTitle, isTournamentOverviewPath } from "./tournament-section-nav";
import { TournamentShellSkeleton } from "./TournamentSkeletons";
import TournamentShellError from "../TournamentShellError";
import { PageHero, HeroCoord, HeroStamp } from "@/components/site/PageHero";
import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { PageStateCard } from "@/components/ui/page-state-card";

type TournamentClientLayoutProps = {
  slug: string;
  children: React.ReactNode;
};

/**
 * The one "players" figure every surface of the page quotes. Registrations
 * count while the field is still forming; once teams exist (`participants_count`
 * is only populated then) the rostered players are the tournament's players —
 * the header and the overview's numbers must not disagree by the withdrawn.
 */
export function tournamentPlayersCount(
  tournament: Pick<Tournament, "participants_count" | "registrations_count" | "teams_count">
): number {
  const rostered = tournament.participants_count ?? 0;
  return (tournament.teams_count ?? 0) > 0 && rostered > 0
    ? rostered
    : (tournament.registrations_count ?? 0);
}

/**
 * Whether the page's header block — the overview's hero, or the one-row header
 * every other section gets — has scrolled under the site header. Drives the rail's
 * collapsed slots: the rail is the only sticky surface this page adds under the
 * site header, so the tournament's name moves INTO it rather than into a second
 * bar. `false` on the server and until the observer fires, so SSR never renders
 * the collapsed state.
 */
function useScrolledPast<T extends HTMLElement>(): [(node: T | null) => void, boolean] {
  const [past, setPast] = React.useState(false);
  const observerRef = React.useRef<IntersectionObserver | null>(null);
  // A callback ref, not an effect on mount: the hero mounts AFTER the shell's
  // skeleton, so a mount-time effect would observe nothing.
  const attach = React.useCallback((node: T | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => setPast(!entry.isIntersecting && entry.boundingClientRect.top < 0),
      // The site header covers the top 3.5rem; the hero counts as gone once it
      // slides under that band, not only once it leaves the window.
      { rootMargin: "-56px 0px 0px 0px" }
    );
    observer.observe(node);
    observerRef.current = observer;
  }, []);
  React.useEffect(() => () => observerRef.current?.disconnect(), []);
  return [attach, past];
}

export default function TournamentClientLayout({
  slug,
  children
}: Readonly<TournamentClientLayoutProps>) {
  const t = useTranslations();
  const format = useFormatter();
  const pathname = usePathname();
  const tournamentQuery = useTournamentQuery(slug);
  const tournament = tournamentQuery.data;
  // Known immediately once the overview resolves; `undefined` while pending —
  // every hook below already tolerates that (see their `| undefined` params),
  // so the realtime subscription and streams query start the instant the
  // numeric id is known instead of waiting for the render past the early
  // returns below.
  const tournamentId = tournament?.id;

  // The page's single invalidation subscription: every section under this shell
  // reads keys the tournament scope owns (overview, teams, standings, brackets,
  // streams), so one consumer keeps all of them fresh. That includes the section
  // rail: it is derived from the overview query (`stages`, `teams_count`), which
  // `tournament.structure` invalidates — no server re-render (`router.refresh()`)
  // is needed, and one per viewer per event is what saturated the frontend.
  //
  // `detailRef` is the URL segment, not the numeric id: the overview query stays
  // keyed by the ref it was fetched with for its whole lifecycle.
  useInvalidation({
    scopeKind: "tournament",
    scopeId: tournamentId,
    workspaceId: tournament?.workspace_id,
    detailRef: slug,
  });

  // Object-local queries and actions must not change the saved viewing filter.
  useEntityWorkspace(tournament?.workspace_id);

  // The shell owns the tournament's streams, for two consumers that outlive any
  // one section: the persistent broadcast block below the hero, and the Stream
  // tab's present-or-absent gate in the nav.
  //
  // Both are gated on the phase (`areStreamsVisible`) at the SOURCE rather than
  // at each render site: a registration-phase page then makes no stream read,
  // and the two consumers go quiet on their own — the dock renders nothing
  // without officials, the nav tab nothing without entries. Freshness needs no
  // subscription of its own: `tournament.streams` arrives on the invalidation
  // topic above, and an invalidation of a key nobody observes costs nothing.
  const streamsTournamentId =
    tournament && areStreamsVisible(tournament.status) ? tournamentId : undefined;
  const streams = useTournamentStreamsQuery(streamsTournamentId).data;

  const [heroRef, heroScrolledPast] = useScrolledPast<HTMLDivElement>();

  // The chrome is still resolving, but the tab below it is NOT waiting on this
  // query: each tab page is a server component that prefetched its own reads
  // and hydrated them around its view, so `{children}` already has content to
  // render — into the streamed HTML on the first request, which is the whole
  // point of the prefetch. Gating it on the shell would keep every public
  // tournament page a skeleton for crawlers and for the first paint alike.
  if (tournamentQuery.isPending) {
    return (
      <div className="aqt-tn space-y-4">
        <TournamentShellSkeleton />
        <section className="min-w-0">{children}</section>
      </div>
    );
  }

  if (tournamentQuery.isError) {
    return <TournamentShellError />;
  }

  if (!tournament) {
    return (
      <div className="aqt-tn">
        <PageStateCard state="not-found" title={t("common.tournamentNotFound")} />
      </div>
    );
  }

  const stages = tournament.stages;
  const teamsCount = tournament.teams_count ?? 0;
  const players = tournamentPlayersCount(tournament);

  const isEnded = isTournamentStatusEnded(tournament.status);
  const statusVariant = getTournamentStatusMeta(tournament.status).variant;
  const overviewHref = `/tournaments/${tournament.slug}`;
  // The full hero belongs to the section it describes. Resolved exactly the way
  // the rail resolves its own active tab, so the two cannot disagree.
  const isOverviewSection = isTournamentOverviewPath(pathname, tournament.slug);
  // The draft room is an external route, so it cannot be a rail tab. It appears
  // once registration is over — before that there is no room to open, and
  // "before" now includes the announcement phase that precedes registration.
  const showDraftLink =
    tournament.team_formation === "draft" && reachedAtLeast(tournament.status, "check_in");

  // The draft room is an external route, so it cannot be a rail tab; it stands
  // in the action row as its own button (wireframes §2 ④). Team formation used
  // to carry this link as a pill, because the row then held nothing else for an
  // ended tournament — with the organizer's links moved into the overview that
  // trade is gone, and the formation itself reads in the Format card, beside the
  // roster shape a pill could not show.
  const draftButton = showDraftLink ? (
    <HoverPrefetchLink href={`/draft/${tournament.slug}`} className={TOURNAMENT_ACTION_CLASS}>
      {t("common.draft")}
      <ExternalLink className="size-3.5 opacity-80" aria-hidden />
    </HoverPrefetchLink>
  ) : null;

  const registerButton = !isEnded ? <TournamentRegisterButton tournament={tournament} /> : null;
  const nextPhaseChip = <NextPhaseChip tournament={tournament} href={`${overviewHref}#phases`} />;

  return (
    <div className="aqt-tn space-y-4">
      {tournament.is_hidden && (
        <div
          role="status"
          className="rounded-xl border px-4 py-3"
          style={{
            borderColor: "var(--aqt-border)",
            background: "var(--aqt-overlay-2)"
          }}
        >
          <p className="text-sm font-semibold">{t("tournamentDetail.previewBanner")}</p>
          <p className="text-xs opacity-70">{t("tournamentDetail.previewBannerDescription")}</p>
        </div>
      )}
      {isOverviewSection ? (
        <div ref={heroRef}>
          <PageHero
            /* Cover fades in from the right. Without one, only the CTAs move
               into that column — stamps stay under the title. */
            coverUrl={tournament.cover_image_url}
            coverFade={tournament.cover_image_url ? "right" : undefined}
            align={tournament.cover_image_url ? "start" : "end"}
            eyebrow={
              <HeroCoord className="inline-flex flex-wrap items-center gap-x-4 gap-y-1">
                <HoverPrefetchLink
                  href="/tournaments"
                  className="transition-colors hover:text-[color:var(--aqt-teal)]"
                >
                  {t("common.tournaments")}
                </HoverPrefetchLink>
                <span className="opacity-50">/</span>
                <span>{formatDateRange(format, tournament.start_date, tournament.end_date)}</span>
                {tournament.is_league ? (
                  <>
                    <span className="opacity-50">/</span>
                    <span>{t("common.league")}</span>
                  </>
                ) : null}
              </HeroCoord>
            }
            title={
              <span className="flex flex-wrap items-center gap-x-3 gap-y-2">
                {tournament.logo_url ? (
                  /* Plain `<img>`, like every other S3 image on the site: the URL
                     points at whatever host the deployment configured, and
                     `next/image` hard-errors on a hostname missing from
                     `remotePatterns`. Decorative — the h1 beside it is the name. */
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={tournament.logo_url}
                    alt=""
                    aria-hidden
                    width={56}
                    height={56}
                    loading="lazy"
                    decoding="async"
                    className="size-14 shrink-0 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg)] object-cover"
                  />
                ) : null}
                <span className="min-w-0">{tournament.name}</span>
                <TournamentStatusPill status={statusVariant} className="shrink-0">
                  {t(`common.statusBadge.${tournament.status}`)}
                </TournamentStatusPill>
              </span>
            }
            stamp={
              <span className="flex w-full flex-col items-start gap-5">
                <span className="flex flex-wrap items-end gap-x-8 gap-y-3">
                  <NextPhaseChip
                    variant="stamp"
                    tournament={tournament}
                    href={`${overviewHref}#phases`}
                  />
                  {teamsCount > 0 || tournament.team_formation === "registration" ? (
                    <HeroStamp
                      label={t(tournament.team_formation === "registration" ? "registrationTeams.list.inTournament" : "tournamentDetail.overview.numbers.teams")}
                      value={teamsCount}
                    />
                  ) : null}
                  <HeroStamp label={t("common.playersLabel")} value={players} />
                </span>
                {tournament.cover_image_url && (registerButton || draftButton) ? (
                  <span className="flex flex-wrap items-center gap-2.5">
                    {registerButton}
                    {draftButton}
                  </span>
                ) : null}
              </span>
            }
            aside={
              tournament.cover_image_url || !(registerButton || draftButton) ? undefined : (
                <div className="flex flex-wrap items-center gap-2.5 lg:justify-end">
                  {registerButton}
                  {draftButton}
                </div>
              )
            }
          />
        </div>
      ) : (
        /* Every other section opens on its own content. The banner, the
           breadcrumb and the stamps are the overview's answer to "what is this
           tournament"; repeating them above a bracket or a match list cost
           ~220px before the content a reader navigated to. What is left is what
           keeps the reader oriented — the mark, the name, the state, the dates —
           in one row, with the actions that are not reachable from any tab. */
        <div
          ref={heroRef}
          className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-3 py-2.5 sm:px-4"
        >
          <HoverPrefetchLink
            href={overviewHref}
            className="flex min-h-10 min-w-0 items-center gap-2.5 transition-colors hover:text-[color:var(--aqt-teal)]"
          >
            {tournament.logo_url ? (
              /* Same plain `<img>` as the hero's, for the same reason. */
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={tournament.logo_url}
                alt=""
                aria-hidden
                width={40}
                height={40}
                loading="lazy"
                decoding="async"
                className="size-10 shrink-0 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg)] object-cover"
              />
            ) : null}
            <span className="truncate font-onest text-base font-bold leading-tight">
              {tournament.name}
            </span>
          </HoverPrefetchLink>
          <TournamentStatusPill status={statusVariant} className="shrink-0">
            {t(`common.statusBadge.${tournament.status}`)}
          </TournamentStatusPill>
          <span className="text-caption text-[color:var(--aqt-fg-faint)]">
            {formatDateRange(format, tournament.start_date, tournament.end_date)}
          </span>
          {registerButton || draftButton ? (
            <span className="ms-auto flex flex-wrap items-center gap-2.5">
              {registerButton}
              {draftButton}
            </span>
          ) : null}
        </div>
      )}

      <TournamentSectionNav
        tournamentId={tournament.slug}
        status={tournament.status}
        stages={stages}
        hasTeams={teamsCount > 0}
        hasStreams={(streams?.official?.length ?? 0) > 0 || (streams?.participants?.length ?? 0) > 0}
        hasRules={Boolean(tournament.rules?.trim())}
        collapsed={heroScrolledPast}
        collapsedTitle={
          <span title={tournament.name}>{collapsedRailTitle(tournament.name)}</span>
        }
        collapsedActions={
          <>
            {nextPhaseChip}
            {registerButton}
          </>
        }
      />

      <section className="min-w-0">{children}</section>

      {/* Fixed to the bottom-trailing corner, so it takes no room in this
          stack. Rendered LAST on purpose: a complementary panel that a
          keyboard user reaches after the section content, rather than two tab
          stops standing in front of every page. */}
      <TournamentBroadcastDock streams={streams} />
    </div>
  );
}
