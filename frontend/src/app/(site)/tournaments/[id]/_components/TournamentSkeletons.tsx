"use client";

import React from "react";
import { useTranslations } from "next-intl";

import { PageHero } from "@/components/site/PageHero";
import { cn } from "@/lib/utils";

import styles from "../TournamentDetail.module.css";

type SkeletonBlockProps = React.HTMLAttributes<HTMLSpanElement>;

function SkeletonBlock({ className, ...props }: SkeletonBlockProps) {
  return <span aria-hidden="true" className={cn(styles.skeletonBlock, className)} {...props} />;
}

function SkeletonRegion({
  variant,
  message,
  children
}: {
  variant: "shell" | "bracket" | "teams" | "participants" | "matches" | "heroes" | "standings";
  message: string;
  children: React.ReactNode;
}) {
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

function PageHeadingSkeleton({ action = false }: { action?: boolean }) {
  return (
    <header className={styles.skeletonHeader}>
      <div className={styles.skeletonHeaderText}>
        <SkeletonBlock style={{ width: "5.5rem", height: "0.55rem" }} />
        <SkeletonBlock style={{ width: "min(16rem, 72vw)", height: "1.85rem" }} />
        <SkeletonBlock style={{ width: "min(24rem, 80vw)", height: "0.7rem" }} />
      </div>
      {action ? <SkeletonBlock style={{ width: "7.5rem", height: "2.25rem" }} /> : null}
    </header>
  );
}

function ControlRowSkeleton({ search = false }: { search?: boolean }) {
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

function TableRowsSkeleton({ count = 6 }: { count?: number }) {
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

function TournamentPageSkeletonLayout({ children }: { children: React.ReactNode }) {
  return <div className={styles.skeletonStack}>{children}</div>;
}

export function TournamentShellSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion variant="shell" message={t("common.loading")}>
      <div className="aqt-tn min-w-0 space-y-4">
        <PageHero
          eyebrow={<SkeletonBlock style={{ width: "14rem", height: "0.65rem" }} />}
          title={<SkeletonBlock style={{ width: "min(32rem, 76vw)", height: "3rem" }} />}
          meta={
            <>
              <SkeletonBlock style={{ width: "5rem", height: "1.75rem" }} />
              <SkeletonBlock style={{ width: "7rem", height: "1.75rem" }} />
              <SkeletonBlock style={{ width: "6rem", height: "1.75rem" }} />
            </>
          }
          lede={
            <span className="grid gap-2">
              <SkeletonBlock style={{ width: "min(28rem, 74vw)", height: "0.7rem" }} />
              <SkeletonBlock style={{ width: "min(21rem, 58vw)", height: "0.7rem" }} />
            </span>
          }
          aside={
            <div className="grid grid-cols-2 gap-x-7 gap-y-5 xl:grid-cols-4">
              {Array.from({ length: 4 }, (_, index) => (
                <div className="grid gap-2" key={index}>
                  <SkeletonBlock style={{ width: "4rem", height: "0.55rem" }} />
                  <SkeletonBlock style={{ width: "3rem", height: "2rem" }} />
                  <SkeletonBlock style={{ width: "3.5rem", height: "0.55rem" }} />
                </div>
              ))}
            </div>
          }
        />

        <div className={styles.navRegion} data-shell-region="tabs">
          <div className={styles.phaseNote}>
            <SkeletonBlock style={{ width: "min(26rem, 74vw)", height: "0.55rem" }} />
          </div>
          <div className={styles.railFrame}>
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

        <div className={styles.skeletonSurface} style={{ padding: "1.5rem" }}>
          <PageHeadingSkeleton action />
          <div className={styles.skeletonGrid} style={{ marginTop: "1.5rem" }}>
            {Array.from({ length: 3 }, (_, index) => (
              <SkeletonBlock key={index} style={{ height: "8.5rem" }} />
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
        <PageHeadingSkeleton />
        <ControlRowSkeleton />
        <div className={styles.skeletonSurface}>
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
        <PageHeadingSkeleton />
        <ControlRowSkeleton />
        <div className={styles.skeletonGrid}>
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

export function TournamentParticipantsSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion
      variant="participants"
      message={t("tournamentDetail.loading.pages.participants")}
    >
      <TournamentPageSkeletonLayout>
        <PageHeadingSkeleton />
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
        <PageHeadingSkeleton />
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
        <PageHeadingSkeleton />
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

export function TournamentStandingsSkeleton() {
  const t = useTranslations();

  return (
    <SkeletonRegion variant="standings" message={t("tournamentDetail.loading.pages.standings")}>
      <TournamentPageSkeletonLayout>
        <PageHeadingSkeleton />
        <ControlRowSkeleton />
        {[0, 1].map((card) => (
          <div className={styles.skeletonSurface} key={card}>
            <div className={styles.skeletonHeader} style={{ padding: "1rem" }}>
              <SkeletonBlock style={{ width: "11rem", height: "1.25rem" }} />
              <SkeletonBlock style={{ width: "4rem", height: "1.25rem" }} />
            </div>
            <TableRowsSkeleton count={5} />
          </div>
        ))}
      </TournamentPageSkeletonLayout>
    </SkeletonRegion>
  );
}
