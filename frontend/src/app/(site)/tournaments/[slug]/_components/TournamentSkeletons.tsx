"use client";

import React from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { PageHero } from "@/components/site/PageHero";
import { cn } from "@/lib/utils";

import styles from "../TournamentDetail.module.css";
import { isTournamentOverviewPath } from "./tournament-section-nav";

type SkeletonBlockProps = React.HTMLAttributes<HTMLSpanElement>;

function SkeletonBlock({ className, ...props }: SkeletonBlockProps) {
  return <span aria-hidden="true" className={cn(styles.skeletonBlock, className)} {...props} />;
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
      className={styles.skeletonRegion}
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
    <div className={styles.skeletonControls}>
      <SkeletonBlock style={{ width: "5.75rem", height: "2.15rem", flex: "0 0 auto" }} />
      <SkeletonBlock style={{ width: "6.5rem", height: "2.15rem", flex: "0 0 auto" }} />
      <SkeletonBlock style={{ width: "5.25rem", height: "2.15rem", flex: "0 0 auto" }} />
      {search ? (
        <SkeletonBlock
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
    <div className={styles.skeletonRows}>
      {Array.from({ length: count }, (_, index) => (
        <div className={styles.skeletonRow} key={index}>
          <SkeletonBlock style={{ width: index % 2 ? "72%" : "86%", height: "0.85rem" }} />
          <SkeletonBlock style={{ width: "68%", height: "0.7rem" }} />
          <SkeletonBlock style={{ width: "2.5rem", height: "1.15rem", justifySelf: "end" }} />
        </div>
      ))}
    </div>
  );
}

function TournamentPageSkeletonLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <div className={styles.skeletonStack}>{children}</div>;
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
      <div className="aqt-tn min-w-0 space-y-4">
        {isOverview ? (
          <PageHero
            align="start"
            eyebrow={<SkeletonBlock style={{ width: "14rem", height: "0.65rem" }} />}
            title={<SkeletonBlock style={{ width: "min(28rem, 70vw)", height: "2.4rem" }} />}
            meta={
              <>
                <SkeletonBlock style={{ width: "5rem", height: "1.75rem" }} />
                <SkeletonBlock style={{ width: "9rem", height: "1.75rem" }} />
                <SkeletonBlock style={{ width: "7rem", height: "1.75rem" }} />
                <SkeletonBlock style={{ width: "6rem", height: "1.75rem" }} />
              </>
            }
          />
        ) : (
          /* The compact header's own box: 40px mark, name, state, in the same
             framed row at the same height. */
          <div
            className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-3 py-2.5 sm:px-4"
            data-shell-region="compact-header"
          >
            <SkeletonBlock style={{ width: "2.5rem", height: "2.5rem", flex: "0 0 auto" }} />
            <SkeletonBlock style={{ width: "min(18rem, 50vw)", height: "1.25rem" }} />
            <SkeletonBlock style={{ width: "5rem", height: "1.25rem", flex: "0 0 auto" }} />
          </div>
        )}

        <div className={styles.navRegion} data-shell-region="tabs">
          <div className={cn(styles.railFrame, styles.railFrameWithControls)}>
            <SkeletonBlock style={{ width: "2rem", height: "2.75rem" }} />
            <div className={styles.skeletonControls}>
              {Array.from({ length: 6 }, (_, index) => (
                <SkeletonBlock
                  key={index}
                  style={{
                    width: index % 2 ? "5.5rem" : "6.5rem",
                    height: "2.75rem",
                    flex: "0 0 auto"
                  }}
                />
              ))}
            </div>
            <SkeletonBlock style={{ width: "2rem", height: "2.75rem" }} />
          </div>
        </div>

      </div>
    </SkeletonRegion>
  );
}

/**
 * The overview's 7/3 shape (wireframes §3): one full-width block on top — the
 * phase timeline in registration, the live/podium card afterwards — then the
 * "now" column beside the reference column. Reserving both columns matters more
 * here than on any other section: the overview is the landing page, so this is
 * the first paint of the whole tournament.
 */
export function TournamentOverviewSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion variant="overview" message={t("tournamentDetail.overview.loading")}>
      <TournamentPageSkeletonLayout>
        <div className={styles.skeletonSurface}>
          <div className={styles.skeletonHeader} style={{ padding: "1rem" }}>
            <SkeletonBlock style={{ width: "9rem", height: "1.25rem" }} />
          </div>
          <div className="grid gap-2 p-4 sm:grid-cols-4">
            {Array.from({ length: 4 }, (_, cell) => (
              <div className="grid gap-1.5" key={cell}>
                <SkeletonBlock style={{ width: "70%", height: "0.85rem" }} />
                <SkeletonBlock style={{ width: "90%", height: "0.7rem" }} />
              </div>
            ))}
          </div>
        </div>
        <div className="grid gap-4 lg:grid-cols-[7fr_3fr]">
          <div className="grid content-start gap-4">
            {[0, 1].map((card) => (
              <div className={styles.skeletonSurface} key={card}>
                <div className={styles.skeletonHeader} style={{ padding: "1rem" }}>
                  <SkeletonBlock style={{ width: "8rem", height: "1rem" }} />
                </div>
                <div className="grid gap-2 p-4 sm:grid-cols-2">
                  {Array.from({ length: 2 }, (_, tile) => (
                    <SkeletonBlock key={tile} style={{ width: "100%", height: "5rem" }} />
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="grid content-start gap-4">
            {[0, 1, 2].map((card) => (
              <div className={styles.skeletonSurface} key={card}>
                <div className={styles.skeletonHeader} style={{ padding: "1rem" }}>
                  <SkeletonBlock style={{ width: "6.5rem", height: "1rem" }} />
                </div>
                <div className="grid gap-2 p-4">
                  <SkeletonBlock style={{ width: "100%", height: "0.7rem" }} />
                  <SkeletonBlock style={{ width: "80%", height: "0.7rem" }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </TournamentPageSkeletonLayout>
    </SkeletonRegion>
  );
}

export function TournamentBracketSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion variant="bracket" message={t("tournamentDetail.loading.pages.bracket")}>
      <TournamentPageSkeletonLayout>
        
        <div className={styles.skeletonSurface}>
          <div
            className={styles.skeletonHeader}
            data-skeleton-region="bracket-toolbar"
            style={{ padding: "1rem" }}
          >
            <div className={styles.skeletonControls}>
              <SkeletonBlock style={{ width: "6.5rem", height: "2.15rem" }} />
              <SkeletonBlock style={{ width: "5.5rem", height: "2.15rem" }} />
            </div>
            <div className={styles.skeletonControls}>
              <SkeletonBlock style={{ width: "5.5rem", height: "2.15rem" }} />
              <SkeletonBlock style={{ width: "4.75rem", height: "2.15rem" }} />
            </div>
          </div>
          <div className={styles.bracketFrame}>
            {Array.from({ length: 3 }, (_, column) => (
              <div className={styles.bracketColumn} key={column}>
                <SkeletonBlock style={{ width: "6rem", height: "0.65rem" }} />
                <SkeletonBlock style={{ height: "5rem" }} />
                <SkeletonBlock style={{ height: "5rem" }} />
              </div>
            ))}
          </div>
        </div>
      </TournamentPageSkeletonLayout>
    </SkeletonRegion>
  );
}

export function TournamentTeamsSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion variant="teams" message={t("tournamentDetail.loading.pages.teams")}>
      <TournamentPageSkeletonLayout>
        
        <ControlRowSkeleton />
        <div className={styles.teamsSkeletonGrid}>
          {Array.from({ length: 6 }, (_, card) => (
            <div className={styles.skeletonCard} key={card}>
              <SkeletonBlock style={{ width: "72%", height: "1.15rem" }} />
              <SkeletonBlock style={{ width: "46%", height: "0.65rem" }} />
              <SkeletonBlock style={{ width: "100%", height: "1px" }} />
              <SkeletonBlock style={{ width: "88%", height: "2.5rem" }} />
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
        <div className={styles.skeletonSurface}>
          <div className={styles.skeletonRow}>
            <SkeletonBlock style={{ width: "8rem", height: "0.55rem" }} />
            <SkeletonBlock style={{ width: "6rem", height: "0.55rem" }} />
            <SkeletonBlock style={{ width: "3rem", height: "0.55rem", justifySelf: "end" }} />
          </div>
          <TableRowsSkeleton count={8} />
        </div>
      </TournamentPageSkeletonLayout>
    </SkeletonRegion>
  );
}

export function TournamentMatchesSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion variant="matches" message={t("tournamentDetail.loading.pages.matches")}>
      <TournamentPageSkeletonLayout>
        
        <div className={styles.skeletonControls}>
          <SkeletonBlock style={{ width: "min(18rem, 76vw)", height: "2.25rem" }} />
        </div>
        <div className={styles.skeletonSurface}>
          <div className={styles.skeletonRow}>
            <SkeletonBlock style={{ width: "7rem", height: "0.55rem" }} />
            <SkeletonBlock style={{ width: "5rem", height: "0.55rem" }} />
            <SkeletonBlock style={{ width: "3rem", height: "0.55rem", justifySelf: "end" }} />
          </div>
          <TableRowsSkeleton count={7} />
        </div>
        <div className={styles.skeletonControls} style={{ justifyContent: "flex-end" }}>
          <SkeletonBlock style={{ width: "13rem", height: "2.25rem" }} />
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
        <div className={styles.skeletonSurface}>
          {Array.from({ length: 8 }, (_, index) => (
            <div className={styles.heroSkeletonRow} key={index}>
              <SkeletonBlock style={{ width: "78%", height: "1.6rem" }} />
              <SkeletonBlock style={{ width: `${92 - index * 6}%`, height: "0.45rem" }} />
              <SkeletonBlock style={{ width: "2.4rem", height: "0.75rem" }} />
            </div>
          ))}
        </div>
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
        <div className={styles.skeletonSurface}>
          <div className={styles.skeletonRows}>
            {Array.from({ length: 3 }, (_, row) => (
              <div className={styles.skeletonRow} key={row}>
                <SkeletonBlock style={{ width: "7rem", height: "0.55rem" }} />
                <SkeletonBlock style={{ width: "100%", height: "3.5rem" }} />
              </div>
            ))}
          </div>
        </div>
        <div className={styles.skeletonSurface}>
          <TableRowsSkeleton count={4} />
        </div>
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
        <div className={styles.skeletonSurface}>
          <div className="flex items-center justify-between gap-4 border-b border-[color:var(--aqt-border)] px-5 py-3">
            <SkeletonBlock style={{ width: "7rem", height: "1rem" }} />
            <SkeletonBlock style={{ width: "8rem", height: "1.4rem" }} />
          </div>
          <div className="grid xl:grid-cols-[minmax(0,1fr)_340px]">
            <div className="flex min-w-0 flex-col">
              <SkeletonBlock className="aspect-video min-h-[300px] w-full rounded-none border-0" />
              <div className="flex flex-col gap-2.5 p-4">
                <SkeletonBlock style={{ width: "12rem", height: "1.4rem" }} />
                <SkeletonBlock style={{ width: "16rem", height: "1.15rem" }} />
                <SkeletonBlock style={{ width: "70%", height: "0.85rem" }} />
                <SkeletonBlock style={{ width: "9rem", height: "2.2rem" }} />
              </div>
            </div>
            <div className="grid content-start gap-2 border-t border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-3 md:grid-cols-2 xl:grid-cols-1 xl:border-t-0 xl:border-s">
              {Array.from({ length: 4 }, (_, row) => (
                <div className="flex items-center gap-3 p-2" key={row}>
                  <SkeletonBlock className="aspect-video w-[104px] shrink-0" />
                  <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                    <SkeletonBlock style={{ width: row % 2 ? "58%" : "72%", height: "0.85rem" }} />
                    <SkeletonBlock style={{ width: "40%", height: "0.7rem" }} />
                    <SkeletonBlock style={{ width: row % 2 ? "80%" : "64%", height: "0.7rem" }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </TournamentPageSkeletonLayout>
    </SkeletonRegion>
  );
}
