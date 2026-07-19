import { useTranslations } from "next-intl";
import type { HTMLAttributes, ReactNode } from "react";

import styles from "./DraftRoom.module.css";

type SkeletonBlockProps = HTMLAttributes<HTMLSpanElement>;

function SkeletonBlock({ className = "", ...props }: SkeletonBlockProps) {
  return <span aria-hidden="true" className={`${styles.skeletonBlock} ${className}`} {...props} />;
}

function LoadingRegion({ className, children }: { className: string; children: ReactNode }) {
  const t = useTranslations("draftRedesign");

  return (
    <div
      className={className}
      role="status"
      aria-live="polite"
      aria-busy="true"
      data-skeleton-variant="draft"
    >
      <span className="sr-only">{t("loadingTitle")}</span>
      <div aria-hidden="true">{children}</div>
    </div>
  );
}

function DraftSkeletonToolbar() {
  return (
    <header className={`${styles.toolbar} ${styles.skeletonToolbar}`} data-draft-skeleton="toolbar">
      <div className={styles.skeletonToolbarInner}>
        <div className={styles.skeletonBackAction} data-draft-skeleton="back-action">
          <SkeletonBlock className={styles.skeletonBackArrow} />
          <SkeletonBlock className={styles.skeletonBackLabel} />
        </div>
        <div className={styles.skeletonToolbarName}>
          <SkeletonBlock className={styles.skeletonMicrocopy} />
          <SkeletonBlock className={styles.skeletonToolbarTitle} />
        </div>
        <div className={styles.skeletonPublicIndicator}>
          <SkeletonBlock className={styles.skeletonSignal} />
          <SkeletonBlock className={styles.skeletonPublicLabel} />
        </div>
      </div>
      <span className={styles.rail} />
    </header>
  );
}

function DraftHeroSkeleton() {
  return (
    <section className={styles.skeletonHero} data-draft-skeleton="standalone-hero">
      <span className={styles.skeletonHeroAccent} />
      <div className={styles.skeletonHeroCopy}>
        <div className={styles.skeletonHeroMeta}>
          <SkeletonBlock className={styles.skeletonEyebrow} />
          <SkeletonBlock className={styles.skeletonStatusPill} />
        </div>
        <SkeletonBlock className={styles.skeletonHeroTitle} />
        <SkeletonBlock className={styles.skeletonHeroLede} />
        <SkeletonBlock className={styles.skeletonHeroLedeShort} />
        <div className={styles.skeletonHeroStamps}>
          <SkeletonBlock />
          <SkeletonBlock />
          <SkeletonBlock />
        </div>
      </div>
      <div className={styles.skeletonStatusSummary} data-draft-skeleton="status-summary">
        {Array.from({ length: 3 }, (_, index) => (
          <div className={styles.skeletonMetric} key={index}>
            <SkeletonBlock className={styles.skeletonMetricLabel} />
            <SkeletonBlock className={styles.skeletonMetricValue} />
          </div>
        ))}
      </div>
    </section>
  );
}

function PickSlotSkeleton({ compact = false }: { compact?: boolean }) {
  return (
    <div
      className={`${styles.skeletonPickSlot} ${compact ? styles.skeletonPickSlotCompact : ""}`}
      data-draft-skeleton="pick-slot"
    >
      <SkeletonBlock className={styles.skeletonSlotBadge} />
      <div className={styles.skeletonSlotCopy}>
        <SkeletonBlock className={styles.skeletonSlotName} />
        <SkeletonBlock className={styles.skeletonSlotMeta} />
      </div>
      <SkeletonBlock className={styles.skeletonSlotRole} />
    </div>
  );
}

function RosterColumnSkeleton({ side }: { side: "left" | "right" }) {
  return (
    <section
      className={`${styles.skeletonWorkspaceColumn} ${styles.skeletonRosterColumn}`}
      data-draft-skeleton={`roster-${side}`}
    >
      <div className={styles.skeletonColumnHeading}>
        <div>
          <SkeletonBlock className={styles.skeletonMicrocopy} />
          <SkeletonBlock className={styles.skeletonColumnTitle} />
        </div>
        <SkeletonBlock className={styles.skeletonRosterPosition} />
      </div>
      <div className={styles.skeletonSlotStack}>
        {Array.from({ length: 3 }, (_, index) => (
          <PickSlotSkeleton compact key={index} />
        ))}
      </div>
    </section>
  );
}

function BoardColumnSkeleton() {
  return (
    <section className={styles.skeletonWorkspaceColumn} data-draft-skeleton="board">
      <div className={styles.skeletonBoardHeading}>
        <div>
          <SkeletonBlock className={styles.skeletonMicrocopy} />
          <SkeletonBlock className={styles.skeletonBoardTitle} />
        </div>
        <SkeletonBlock className={styles.skeletonBoardCount} />
      </div>
      <div className={styles.skeletonFilterRail}>
        <SkeletonBlock className={styles.skeletonSearch} />
        <SkeletonBlock className={styles.skeletonFilter} />
        <SkeletonBlock className={styles.skeletonFilter} />
      </div>
      <div className={styles.skeletonBoardRows}>
        {Array.from({ length: 4 }, (_, index) => (
          <PickSlotSkeleton key={index} />
        ))}
      </div>
    </section>
  );
}

function DraftWorkspaceSkeleton() {
  return (
    <div className={styles.skeletonWorkspace}>
      <DraftHeroSkeleton />

      <div className={styles.skeletonConnectionRail}>
        <SkeletonBlock className={styles.skeletonConnectionState} />
        <SkeletonBlock className={styles.skeletonConnectionMeta} />
      </div>

      <section className={styles.skeletonCurrentPick} data-draft-skeleton="board-controls">
        <div className={styles.skeletonCurrentPickCopy}>
          <SkeletonBlock className={styles.skeletonEyebrow} />
          <SkeletonBlock className={styles.skeletonCurrentPickTitle} />
          <SkeletonBlock className={styles.skeletonCurrentPickHint} />
          <div className={styles.skeletonCurrentPickActions}>
            <SkeletonBlock />
            <SkeletonBlock />
          </div>
        </div>
        <div className={styles.skeletonTimer} data-draft-skeleton="timer">
          <SkeletonBlock className={styles.skeletonTimerRing} />
          <SkeletonBlock className={styles.skeletonTimerValue} />
        </div>
      </section>

      <div className={styles.skeletonWorkspaceGrid}>
        <RosterColumnSkeleton side="left" />
        <BoardColumnSkeleton />
        <RosterColumnSkeleton side="right" />
      </div>
    </div>
  );
}

export function DraftRoomSkeleton() {
  return (
    <LoadingRegion className={`${styles.room} ${styles.skeletonRoom} site-theme`}>
      <DraftSkeletonToolbar />
      <main className={`${styles.stage} ${styles.skeletonStage}`}>
        <DraftWorkspaceSkeleton />
      </main>
    </LoadingRegion>
  );
}

export function DraftBoardSkeleton() {
  return (
    <LoadingRegion className={styles.skeletonBoardRegion}>
      <DraftWorkspaceSkeleton />
    </LoadingRegion>
  );
}
