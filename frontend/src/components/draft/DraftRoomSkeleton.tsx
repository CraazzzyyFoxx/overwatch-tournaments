import { useTranslations } from "next-intl";
import type { HTMLAttributes, ReactNode } from "react";

import styles from "@/components/draft/DraftRoom.module.css";

type SkeletonBlockProps = HTMLAttributes<HTMLSpanElement>;

function SkeletonBlock({ className = "", ...props }: SkeletonBlockProps) {
  return <span aria-hidden="true" className={`${styles.skeletonBlock} ${className}`} {...props} />;
}

function LoadingRegion({ className, children }: Readonly<{ className: string; children: ReactNode }>) {
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

const TICKS = 12;
const POOL_ROWS = 7;
const TEAM_ROWS = 6;

/** Mirrors the loaded room: header row + clock strip, then the pool and teams panels. */
function RoomSkeleton() {
  return (
    <>
      <div className={styles.skeletonHeader} data-draft-skeleton="header">
        <div className={styles.skeletonHeaderRow}>
          <div className={styles.skeletonBackAction} data-draft-skeleton="back-action">
            <SkeletonBlock className={styles.skeletonBackArrow} />
            <SkeletonBlock className={styles.skeletonBackLabel} />
          </div>
          <span className={styles.skeletonDivider} />
          <SkeletonBlock className={styles.skeletonTitle} />
          <SkeletonBlock className={styles.skeletonStatusPill} data-draft-skeleton="status-pill" />
          <div className={styles.skeletonHeaderMeta}>
            <SkeletonBlock className={styles.skeletonFormat} />
            <SkeletonBlock className={styles.skeletonViewers} />
            <SkeletonBlock className={styles.skeletonSeat} />
          </div>
        </div>
        <div className={styles.skeletonStripBand}>
          <div className={styles.skeletonStrip} data-draft-skeleton="clock-strip">
            <SkeletonBlock className={styles.skeletonTimer} data-draft-skeleton="timer" />
            <div className={styles.skeletonWho}>
              <SkeletonBlock className={styles.skeletonEyebrow} />
              <SkeletonBlock className={styles.skeletonWhoName} />
            </div>
            <div className={styles.skeletonProgress}>
              <SkeletonBlock className={styles.skeletonProgressLine} />
              <div className={styles.skeletonTrack} data-draft-skeleton="tick-track">
                {Array.from({ length: TICKS }, (_, index) => (
                  <SkeletonBlock className={styles.skeletonTick} key={index} />
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className={styles.skeletonBody}>
        <section className={styles.skeletonPanel} data-draft-skeleton="pool">
          <div className={styles.skeletonPanelHead}>
            <SkeletonBlock className={styles.skeletonPanelTitle} />
            <div className={styles.skeletonChips}>
              <SkeletonBlock className={styles.skeletonChip} />
              <SkeletonBlock className={styles.skeletonChip} />
              <SkeletonBlock className={styles.skeletonChip} />
            </div>
          </div>
          <div className={styles.skeletonRows}>
            {Array.from({ length: POOL_ROWS }, (_, index) => (
              <div className={styles.skeletonRow} data-draft-skeleton="pool-row" key={index}>
                <SkeletonBlock className={styles.skeletonRowName} />
                <SkeletonBlock className={styles.skeletonRowCell} />
                <SkeletonBlock className={styles.skeletonRowCell} />
                <SkeletonBlock className={styles.skeletonRowCell} />
              </div>
            ))}
          </div>
        </section>
        <section className={styles.skeletonPanel} data-draft-skeleton="teams">
          <div className={styles.skeletonPanelHead}>
            <SkeletonBlock className={styles.skeletonPanelTitle} />
            <div className={styles.skeletonChips}>
              <SkeletonBlock className={styles.skeletonChip} />
              <SkeletonBlock className={styles.skeletonChip} />
            </div>
          </div>
          <div className={styles.skeletonRows}>
            {Array.from({ length: TEAM_ROWS }, (_, index) => (
              <div className={styles.skeletonRow} data-draft-skeleton="team-row" key={index}>
                <SkeletonBlock className={styles.skeletonRowName} />
                <SkeletonBlock className={styles.skeletonRowCell} />
                <SkeletonBlock className={styles.skeletonRowCell} />
                <SkeletonBlock className={styles.skeletonRowCell} />
                <SkeletonBlock className={styles.skeletonRowCell} />
              </div>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}

/** Route-level loading: the page frame is not mounted yet, so this brings the room surface. */
export function DraftRoomSkeleton() {
  return (
    <LoadingRegion className={`${styles.room} ${styles.skeletonRoom} site-theme`}>
      <RoomSkeleton />
    </LoadingRegion>
  );
}

/** Inside the loaded page while the board's first fetch runs. */
export function DraftBoardSkeleton() {
  return (
    <LoadingRegion className={styles.skeletonBoardRegion}>
      <RoomSkeleton />
    </LoadingRegion>
  );
}
