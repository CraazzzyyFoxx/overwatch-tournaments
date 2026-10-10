
import { cn } from "@/lib/utils";
import styles from "@/components/match/EncounterDetail.module.css";

/**
 * Mirrors the real layout: one header card (crumbs, board, series facts), the
 * tab strip, then the map rows of the default tab — so nothing re-flows the
 * moment data arrives.
 */
const Block = ({ className }: { className?: string }) => (
  <span aria-hidden className={cn(styles.skeleton, className)} />
);

export default function Loading() {
  return (
    <div className={styles.surface} aria-busy>
      <div className={cn(styles.card, styles.header)}>
        <div className={styles.headerTop}>
          <Block className="h-3 w-72 max-w-full" />
          <Block className="h-8 w-36 rounded-lg" />
        </div>
        <div className={styles.board}>
          <div className={styles.boardSide}>
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <Block className="h-5 w-40" />
              <Block className="h-3 w-28" />
            </div>
          </div>
          <div className={styles.boardCenter}>
            <Block className="h-12 w-32" />
            <Block className="h-3 w-40" />
            <Block className="h-[18px] w-24" />
          </div>
          <div className={cn(styles.boardSide, styles.boardSideAway)}>
            <div className="flex min-w-0 flex-1 flex-col items-end gap-2">
              <Block className="h-5 w-40" />
              <Block className="h-3 w-28" />
            </div>
          </div>
        </div>
        <div className={styles.headerFoot}>
          <Block className="h-8 w-80 max-w-full" />
        </div>
      </div>

      <div className={styles.tabs}>
        {Array.from({ length: 3 }).map((_, index) => (
          <span key={index} className={styles.tab}>
            <Block className="h-4 w-20" />
          </span>
        ))}
      </div>

      <section>
        <div className={styles.sectionHead}>
          <Block className="h-6 w-28" />
          <Block className="h-3 w-32" />
        </div>
        <div className={cn(styles.card, styles.mapList)}>
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className={styles.mapRow}>
              <Block className={cn(styles.mapIndex, "h-4 w-4")} />
              <Block className={cn(styles.mapThumb, "rounded-[6px]")} />
              <div className={cn(styles.mapIdentity, "gap-2")}>
                <Block className="h-4 w-32" />
                <Block className="h-3 w-24" />
              </div>
              <Block className={cn(styles.mapScore, "h-5 w-12")} />
              <Block className={cn(styles.mapTime, "h-3 w-12")} />
              <Block className={cn(styles.mapAction, "h-8 w-32 rounded-lg")} />
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
