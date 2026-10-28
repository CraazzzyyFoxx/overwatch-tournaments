"use client";

import React from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { PageHero } from "@/components/site/PageHero";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

import { isTournamentOverviewPath } from "./tournament-section-nav";

/** A row of controls standing in for a toolbar. */
const CONTROLS = "flex min-w-0 max-w-full items-center gap-2 overflow-hidden py-0.5";

/** One table row: three cells, the middle one dropped on a phone. */
const TABLE_ROW =
  "grid min-h-15 grid-cols-[minmax(8rem,1.4fr)_minmax(5rem,1fr)_minmax(3rem,0.45fr)] items-center gap-4 border-b border-[color:var(--aqt-border)] px-4 py-2.5 last:border-b-0 max-sm:grid-cols-[minmax(0,1fr)_4rem] max-sm:*:nth-2:hidden";

/** The surface a table or a bracket loads into. */
function SkeletonSurface({ children }: Readonly<{ children: React.ReactNode }>) {
  return <Card className="min-w-0 overflow-hidden">{children}</Card>;
}

function SkeletonRegion({
  variant,
  message,
  children
}: Readonly<{
  variant: "shell" | "overview" | "bracket" | "teams" | "participants" | "schedule" | "matches" | "heroes" | "standings" | "maps" | "stream";
  message: string;
  children: React.ReactNode;
}>) {
  return (
    <div
      className="min-w-0 max-w-full text-[color:var(--aqt-fg)]"
      role="status"
      aria-live="polite"
      aria-busy="true"
      data-skeleton-variant={variant}
    >
      <span className="sr-only">{message}</span>
      <div aria-hidden="true">{children}</div>
    </div>
  );
}


function ControlRowSkeleton({ search = false }: Readonly<{ search?: boolean }>) {
  return (
    <div className={CONTROLS}>
      <Skeleton style={{ width: "5.75rem", height: "2.15rem", flex: "0 0 auto" }} />
      <Skeleton style={{ width: "6.5rem", height: "2.15rem", flex: "0 0 auto" }} />
      <Skeleton style={{ width: "5.25rem", height: "2.15rem", flex: "0 0 auto" }} />
      {search ? (
        <Skeleton
          style={{
            width: "min(18rem, 52vw)",
            height: "2.15rem",
            marginLeft: "auto",
            flex: "0 0 auto"
          }}
        />
      ) : null}
    </div>
  );
}

function TableRowsSkeleton({ count = 6 }: Readonly<{ count?: number }>) {
  return (
    <div className="grid">
      {Array.from({ length: count }, (_, index) => (
        <div className={TABLE_ROW} key={index}>
          <Skeleton style={{ width: index % 2 ? "72%" : "86%", height: "0.85rem" }} />
          <Skeleton style={{ width: "68%", height: "0.7rem" }} />
          <Skeleton style={{ width: "2.5rem", height: "1.15rem", justifySelf: "end" }} />
        </div>
      ))}
    </div>
  );
}

function TournamentPageSkeletonLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <div className="grid gap-4">{children}</div>;
}

export function TournamentShellSkeleton() {
  const t = useTranslations();
  // The resolved shell draws the full hero on the overview and a one-row header
  // on every other section (see `TournamentClientLayout`). Without the same
  // split here the fallback stood ~220px tall in front of a ~60px header, and
  // every direct load of a section jumped once the overview resolved. The slug
  // is not known yet, so the route SHAPE answers it.
  const isOverview = isTournamentOverviewPath(usePathname());

  return (
    <SkeletonRegion variant="shell" message={t("common.loading")}>
      <div className="min-w-0 space-y-4 text-body">
        {isOverview ? (
          <PageHero
            align="start"
            eyebrow={<Skeleton style={{ width: "14rem", height: "0.65rem" }} />}
            title={<Skeleton style={{ width: "min(28rem, 70vw)", height: "2.4rem" }} />}
            meta={<Skeleton style={{ width: "6.5rem", height: "1.5rem" }} />}
            stamp={
              <span className="grid gap-1.5">
                <Skeleton style={{ width: "4rem", height: "0.65rem" }} />
                <Skeleton style={{ width: "11rem", height: "1.9rem" }} />
                <Skeleton style={{ width: "15rem", height: "0.8rem" }} />
              </span>
            }
          />
        ) : (
          /* The compact header's own box: 40px mark, name, state, in the same
             framed row at the same height. */
          <div
            className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-3 py-2.5 sm:px-4"
            data-shell-region="compact-header"
          >
            <Skeleton style={{ width: "2.5rem", height: "2.5rem", flex: "0 0 auto" }} />
            <Skeleton style={{ width: "min(18rem, 50vw)", height: "1.25rem" }} />
            <Skeleton style={{ width: "5rem", height: "1.25rem", flex: "0 0 auto" }} />
          </div>
        )}

        <div
          className="sticky top-14 z-40 min-w-0 max-w-full bg-[linear-gradient(180deg,var(--aqt-bg)_78%,transparent)] pt-2"
          data-shell-region="tabs"
        >
          <div className="grid w-full min-w-0 max-w-full grid-cols-[2rem_minmax(0,1fr)_2rem] items-stretch border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]/96">
            <Skeleton style={{ width: "2rem", height: "2.75rem" }} />
            <div className={CONTROLS}>
              {Array.from({ length: 6 }, (_, index) => (
                <Skeleton
                  key={index}
                  style={{
                    width: index % 2 ? "5.5rem" : "6.5rem",
                    height: "2.75rem",
                    flex: "0 0 auto"
                  }}
                />
              ))}
            </div>
            <Skeleton style={{ width: "2rem", height: "2.75rem" }} />
          </div>
        </div>

      </div>
    </SkeletonRegion>
  );
}

/**
 * The overview's shape: one full-width lead (the phase timeline before the
 * start, the matches or the podium afterwards), then the phase's own column
 * beside the reference column, 2:1. Reserving both columns matters more here
 * than on any other section: the overview is the landing page, so this is the
 * first paint of the whole tournament.
 */
export function TournamentOverviewSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion variant="overview" message={t("tournamentDetail.overview.loading")}>
      <div className="grid gap-10">
        <div className="grid gap-3">
          <Skeleton style={{ width: "9rem", height: "1.4rem" }} />
          <div className="grid gap-1 sm:grid-cols-4">
            {Array.from({ length: 4 }, (_, step) => (
              <div className="grid gap-1.5 border-t-[3px] border-[color:var(--aqt-border)] px-3 pt-2.5" key={step}>
                <Skeleton style={{ width: "60%", height: "0.95rem" }} />
                <Skeleton style={{ width: "85%", height: "0.7rem" }} />
              </div>
            ))}
          </div>
        </div>
        <div className="grid gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] lg:gap-10">
          <div className="grid content-start gap-3">
            <Skeleton style={{ width: "8rem", height: "1.4rem" }} />
            {Array.from({ length: 4 }, (_, row) => (
              <Skeleton key={row} style={{ width: "100%", height: "3.75rem" }} />
            ))}
          </div>
          <div className="grid content-start divide-y divide-[color:var(--aqt-border)]">
            {[0, 1].map((block) => (
              <div className="grid gap-2 py-5 first:pt-0" key={block}>
                <Skeleton style={{ width: "7rem", height: "1.15rem" }} />
                <Skeleton style={{ width: "100%", height: "0.7rem" }} />
                <Skeleton style={{ width: "80%", height: "0.7rem" }} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </SkeletonRegion>
  );
}

export function TournamentBracketSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion variant="bracket" message={t("tournamentDetail.loading.pages.bracket")}>
      <TournamentPageSkeletonLayout>

        <SkeletonSurface>
          <div
            className="flex min-w-0 items-end justify-between gap-4 p-4 max-sm:flex-col max-sm:items-start"
            data-skeleton-region="bracket-toolbar"
          >
            <div className={CONTROLS}>
              <Skeleton style={{ width: "6.5rem", height: "2.15rem" }} />
              <Skeleton style={{ width: "5.5rem", height: "2.15rem" }} />
            </div>
            <div className={CONTROLS}>
              <Skeleton style={{ width: "5.5rem", height: "2.15rem" }} />
              <Skeleton style={{ width: "4.75rem", height: "2.15rem" }} />
            </div>
          </div>
          <div className="grid min-h-120 grid-cols-[repeat(3,minmax(12rem,1fr))] gap-8 overflow-hidden p-6 max-sm:grid-cols-[repeat(3,13rem)]">
            {Array.from({ length: 3 }, (_, column) => (
              <div className="grid content-start gap-14" key={column}>
                <Skeleton style={{ width: "6rem", height: "0.65rem" }} />
                <Skeleton style={{ height: "5rem" }} />
                <Skeleton style={{ height: "5rem" }} />
              </div>
            ))}
          </div>
        </SkeletonSurface>
      </TournamentPageSkeletonLayout>
    </SkeletonRegion>
  );
}

/** Draws the default list view: one collapsed team row per slot, same grid. */
export function TournamentTeamsSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion variant="teams" message={t("tournamentDetail.loading.pages.teams")}>
      <TournamentPageSkeletonLayout>
        <ControlRowSkeleton />
        <div className="space-y-2">
          {Array.from({ length: 8 }, (_, row) => (
            <div
              key={row}
              className="grid grid-cols-[2.75rem_minmax(0,1fr)_auto_1rem] items-center gap-2.5 rounded-xl border border-[color:var(--aqt-overlay-border)] bg-[color:var(--aqt-overlay-1)] px-3.5 pb-3 pt-2.5 sm:grid-cols-[2.75rem_minmax(0,1fr)_auto_auto_1rem] sm:gap-5"
            >
              <Skeleton style={{ width: "1.75rem", height: "1.25rem" }} />
              <span className="grid gap-2">
                <Skeleton style={{ width: row % 2 ? "38%" : "52%", height: "1rem" }} />
                <Skeleton style={{ width: "78%", height: "0.8rem" }} />
              </span>
              <span className="hidden sm:block">
                <Skeleton style={{ width: "3rem", height: "2rem" }} />
              </span>
              <Skeleton style={{ width: "2.5rem", height: "2rem" }} />
              <span />
            </div>
          ))}
        </div>
      </TournamentPageSkeletonLayout>
    </SkeletonRegion>
  );
}

/**
 * Registered-team roster placeholder. Reuses the `teams` grid — same card
 * geometry — but no control row, because the roster has no filters, and the
 * announced message is the shared "loading teams" copy: the roster is what a
 * registration tournament calls its teams.
 */
export function TournamentParticipantsSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion
      variant="participants"
      message={t("tournamentDetail.loading.pages.participants")}
    >
      <TournamentPageSkeletonLayout>

        <ControlRowSkeleton search />
        <SkeletonSurface>
          <div className={TABLE_ROW}>
            <Skeleton style={{ width: "8rem", height: "0.55rem" }} />
            <Skeleton style={{ width: "6rem", height: "0.55rem" }} />
            <Skeleton style={{ width: "3rem", height: "0.55rem", justifySelf: "end" }} />
          </div>
          <TableRowsSkeleton count={8} />
        </SkeletonSurface>
      </TournamentPageSkeletonLayout>
    </SkeletonRegion>
  );
}

export function TournamentMatchesSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion variant="matches" message={t("tournamentDetail.loading.pages.matches")}>
      <TournamentPageSkeletonLayout>

        <div className={CONTROLS}>
          <Skeleton style={{ width: "min(18rem, 76vw)", height: "2.25rem" }} />
        </div>
        <SkeletonSurface>
          <div className={TABLE_ROW}>
            <Skeleton style={{ width: "7rem", height: "0.55rem" }} />
            <Skeleton style={{ width: "5rem", height: "0.55rem" }} />
            <Skeleton style={{ width: "3rem", height: "0.55rem", justifySelf: "end" }} />
          </div>
          <TableRowsSkeleton count={7} />
        </SkeletonSurface>
        <div className={`${CONTROLS} justify-end`}>
          <Skeleton style={{ width: "13rem", height: "2.25rem" }} />
        </div>
      </TournamentPageSkeletonLayout>
    </SkeletonRegion>
  );
}

export function TournamentHeroesSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion variant="heroes" message={t("tournamentDetail.loading.pages.heroes")}>
      <TournamentPageSkeletonLayout>

        <ControlRowSkeleton />
        <SkeletonSurface>
          {Array.from({ length: 8 }, (_, index) => (
            <div
              className="grid min-h-13.5 grid-cols-[minmax(7rem,0.7fr)_minmax(8rem,1.5fr)_3rem] items-center gap-4 border-b border-[color:var(--aqt-border)] px-4 py-2.25"
              key={index}
            >
              <Skeleton style={{ width: "78%", height: "1.6rem" }} />
              <Skeleton style={{ width: `${92 - index * 6}%`, height: "0.45rem" }} />
              <Skeleton style={{ width: "2.4rem", height: "0.75rem" }} />
            </div>
          ))}
        </SkeletonSurface>
      </TournamentPageSkeletonLayout>
    </SkeletonRegion>
  );
}

export function TournamentMapsSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion variant="maps" message={t("tournamentDetail.loading.pages.maps")}>
      <TournamentPageSkeletonLayout>
        <ControlRowSkeleton />
        {/* Two surfaces, because the page has two: the pool grid, then the
            per-round breakdown. One tall block would promise a shape the
            arriving content does not have. */}
        <SkeletonSurface>
          <div className="grid">
            {Array.from({ length: 3 }, (_, row) => (
              <div className={TABLE_ROW} key={row}>
                <Skeleton style={{ width: "7rem", height: "0.55rem" }} />
                <Skeleton style={{ width: "100%", height: "3.5rem" }} />
              </div>
            ))}
          </div>
        </SkeletonSurface>
        <SkeletonSurface>
          <TableRowsSkeleton count={4} />
        </SkeletonSurface>
      </TournamentPageSkeletonLayout>
    </SkeletonRegion>
  );
}

export function TournamentStreamSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion variant="stream" message={t("tournamentDetail.loading.pages.stream")}>
      <TournamentPageSkeletonLayout>
        {/* The theater-and-rail shape `TournamentStreamPage` renders, at the
            same breakpoint, so the arriving player does not shove the rail
            down the page. Four rail rows: more than a handful of participants
            live at once is the rare case, not the one to reserve space for. */}
        <SkeletonSurface>
          <div className="flex items-center justify-between gap-4 border-b border-[color:var(--aqt-border)] px-5 py-3">
            <Skeleton style={{ width: "7rem", height: "1rem" }} />
            <Skeleton style={{ width: "8rem", height: "1.4rem" }} />
          </div>
          <div className="grid xl:grid-cols-[minmax(0,1fr)_340px]">
            <div className="flex min-w-0 flex-col">
              <Skeleton className="aspect-video min-h-[300px] w-full rounded-none" />
              <div className="flex flex-col gap-2.5 p-4">
                <Skeleton style={{ width: "12rem", height: "1.4rem" }} />
                <Skeleton style={{ width: "16rem", height: "1.15rem" }} />
                <Skeleton style={{ width: "70%", height: "0.85rem" }} />
                <Skeleton style={{ width: "9rem", height: "2.2rem" }} />
              </div>
            </div>
            <div className="grid content-start gap-2 border-t border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-3 md:grid-cols-2 xl:grid-cols-1 xl:border-t-0 xl:border-s">
              {Array.from({ length: 4 }, (_, row) => (
                <div className="flex items-center gap-3 p-2" key={row}>
                  <Skeleton className="aspect-video w-[104px] shrink-0" />
                  <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                    <Skeleton style={{ width: row % 2 ? "58%" : "72%", height: "0.85rem" }} />
                    <Skeleton style={{ width: "40%", height: "0.7rem" }} />
                    <Skeleton style={{ width: row % 2 ? "80%" : "64%", height: "0.7rem" }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </SkeletonSurface>
      </TournamentPageSkeletonLayout>
    </SkeletonRegion>
  );
}
