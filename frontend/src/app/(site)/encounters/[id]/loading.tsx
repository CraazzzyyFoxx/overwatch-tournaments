
import { cn } from "@/lib/utils";
import { HeroFrame } from "@/components/site/PageHero";
import styles from "@/components/match/EncounterDetail.module.css";

/**
 * Mirrors the real layout: hero (breadcrumb, title, meta pills, four KPI stats),
 * scoreboard band, map rows, then the two roster panels. The old skeleton still
 * described the retired three-column card layout, so the page visibly re-flowed
 * the moment data arrived.
 */
const Block = ({ className }: { className?: string }) => (
  <span aria-hidden className={cn(styles.skeleton, className)} />
);

export default function Loading() {
  return (
    <div className={styles.surface} aria-busy>
      <HeroFrame>
        <div className="grid gap-8 px-6 py-8 md:px-10 md:py-9 lg:grid-cols-[1.5fr_1fr] lg:gap-12">
          <div className="flex min-w-0 flex-col gap-4">
            <Block className="h-3.5 w-64" />
            <Block className="h-12 w-full max-w-[26rem]" />
            <div className="flex flex-wrap gap-2">
              <Block className="h-6 w-20 rounded-full" />
              <Block className="h-6 w-16 rounded-full" />
              <Block className="h-6 w-28 rounded-full" />
            </div>
            <Block className="h-4 w-full max-w-[30rem]" />
            <div className="mt-2 flex flex-wrap gap-8">
              <Block className="h-9 w-28" />
              <Block className="h-9 w-28" />
            </div>
          </div>
          <div className={styles.heroStats}>
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="flex flex-col gap-2">
                <Block className="h-2.5 w-20" />
                <Block className="h-8 w-24" />
                <Block className="h-2.5 w-28" />
              </div>
            ))}
          </div>
        </div>
      </HeroFrame>

      <div className={styles.card}>
        <div className={styles.board}>
          <div className={styles.boardSide}>
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <Block className="h-5 w-40" />
              <Block className="h-5 w-28 rounded-full" />
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
              <Block className="h-5 w-28 rounded-full" />
            </div>
          </div>
        </div>
      </div>

      <section>
        <div className={styles.sectionHead}>
          <Block className="h-6 w-28" />
          <Block className="h-3 w-32" />
        </div>
        <div className={cn(styles.card, styles.mapList)}>
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className={styles.mapRow}>
              <Block className="h-4 w-4" />
              <Block className="aspect-video w-[6.5rem] rounded-[6px]" />
              <div className="flex min-w-0 flex-col gap-2">
                <Block className="h-4 w-32" />
                <Block className="h-3 w-24" />
              </div>
              <Block className="h-5 w-16" />
              <Block className="h-3 w-full max-w-[10rem]" />
              <Block className="h-8 w-32 rounded-lg" />
            </div>
          ))}
        </div>
      </section>

      <section>
        <div className={styles.sectionHead}>
          <Block className="h-6 w-32" />
        </div>
        <div className={styles.rosterGrid}>
          {Array.from({ length: 2 }).map((_, panel) => (
            <div key={panel} className={styles.card}>
              <div className={styles.rosterHead}>
                <Block className="h-5 w-36" />
                <Block className="h-5 w-24 rounded-full" />
              </div>
              <div className={styles.rosterTable}>
                {Array.from({ length: 5 }).map((_, row) => (
                  <div key={row} className={styles.rosterRow}>
                    <Block className="h-4 w-32" />
                    <Block className="mx-auto h-7 w-7 rounded-full" />
                    <Block className="ml-auto h-4 w-10" />
                    <Block className="mx-auto h-4 w-4 rounded-full" />
                    <Block className="mx-auto h-4 w-4 rounded-full" />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
